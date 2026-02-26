/**
 * app.js — GD Simulator (Streaming + 4-State Turn Machine)
 *
 * States (only one active at a time):
 *   INACTIVE          → before session starts
 *   AI_SPEAKING       → AI streaming + moderator transitioning  (hand raise: allowed, send: blocked)
 *   WAITING_FOR_HAND  → silence timer running                   (hand raise: allowed, send: blocked)
 *   USER_SPEAKING     → user has floor                          (hand raise: hidden, send: visible)
 *   ENDED             → session over
 *
 * Silence timer starts ONLY after the moderator transition message arrives
 * (last "done" chunk) — not during AI streaming.
 */

'use strict';

/* =========================================================
   CONFIG
   ========================================================= */
const BASE_URL = 'http://127.0.0.1:8000';
const SILENCE_DELAY = 5000;   // ms — starts after moderator transition
const SILENCE_JITTER = 1000;   // ±ms natural variation

/* =========================================================
   STATE
   ========================================================= */
const state = {
  sessionId: null,
  isActive: false,
  isEnded: false,
  turnCount: 0,
  uiState: 'INACTIVE',
  streamActive: false,
  handRaisedPending: false,
  restoredMsgCount: 0,
};

let aiRequestCounter = 0;
let aiRequestInFlight = false;


/* =========================================================
   API  (pure fetch wrappers)
   ========================================================= */
const api = {
  async _postJSON(path, params) {
    const url = new URL(`${BASE_URL}${path}`);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url.toString(), { method: 'POST' });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); detail = j.detail || detail; } catch { }
      throw new Error(detail);
    }
    return res.json();
  },

  /**
   * Streaming fetch — yields parsed NDJSON objects line by line.
   * Each object is either {type:"token", text:"..."} or {type:"done", ...}
   */
  async *_postStream(path, params) {
    const url = new URL(`${BASE_URL}${path}`);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url.toString(), { method: 'POST' });
    console.log("AI_SPEAK_RESPONSE_STATUS", res.status);
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); detail = j.detail || detail; } catch { }
      throw new Error(detail);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();  // keep incomplete last chunk
      for (const line of lines) {
        if (line.trim()) yield JSON.parse(line);
      }
    }
    if (buffer.trim()) yield JSON.parse(buffer);   // flush remainder
  },

  start: (topic, duration) => api._postJSON('/start', { topic, duration }),
  raiseHand: (sessionId) => api._postJSON('/raise-hand', { session_id: sessionId }),
  end: (sessionId) => api._postJSON('/end', { session_id: sessionId }),
  speak: (sessionId, msg) => api._postStream('/speak', { session_id: sessionId, message: msg }),
  aiSpeak: (sessionId) => api._postStream('/ai-speak', { session_id: sessionId }),
};

/* =========================================================
   SESSION COUNTDOWN TIMER
   ========================================================= */
const sessionTimer = {
  _h: null,
  _left: 0,
  start(s) {
    this._left = s;
    ui.updateTimer(this._left);
    this._h = setInterval(() => {
      this._left -= 1;
      ui.updateTimer(this._left);
      if (this._left <= 0) {
        this.stop();
        if (!state.isActive) return;
        if (state.streamActive) {
          // A stream is mid-flight — defer endSession until it finishes.
          // The stream handler will call endSession(true) when it completes.
          state.pendingEnd = true;
        } else {
          handlers.endSession(true);
        }
      }
    }, 1000);
  },
  stop() { if (this._h) { clearInterval(this._h); this._h = null; } },
};

/* =========================================================
   SILENCE TIMER
   Starts ONLY after moderator transition message arrives.
   ========================================================= */
const silenceTimer = {
  _h: null,
  reset() {
    console.log("RESET_TRIGGERED");
    this.cancel();
    if (!state.isActive || state.isEnded) return;   // session over
    if (state.pendingEnd) return;                    // awaiting deferred end
    if (state.uiState !== 'WAITING_FOR_HAND') return;
    if (state.streamActive) return;                  // stream in flight
    const delay = SILENCE_DELAY + (Math.random() * SILENCE_JITTER * 2 - SILENCE_JITTER);
    console.log("SET_TIMEOUT_CREATED", delay);
    this._h = setTimeout(() => {
      if (state.uiState === "AI_TURN_ASSIGNED" && !state.isEnded) {
        console.log("CALLING_AI_SPEAK", state, state.sessionId);
        handlers.aiSpeak();
      } else {
        console.log("reset skipped aiSpeak due to state:", state.uiState);
      }
    }, delay);
  },
  cancel() { if (this._h) { clearTimeout(this._h); this._h = null; } },
};

/* =========================================================
   PERSISTENCE  (localStorage — survives page refresh)
   Saves:    session_id, topic, transcript HTML,
             remainingTime (for timer), turnCount, lastMsgCount
   ========================================================= */
const LS_KEY = 'gd_session';
const persist = {
  save() {
    if (!state.sessionId) return;
    try {
      const msgCount = document.querySelectorAll('#transcript .message').length;
      localStorage.setItem(LS_KEY, JSON.stringify({
        sessionId: state.sessionId,
        topic: document.getElementById('status-topic').textContent,
        transcriptHtml: document.getElementById('transcript').innerHTML,
        turnCount: state.turnCount,
        remainingTime: sessionTimer._left,   // seconds left on countdown
        lastMsgCount: msgCount,             // bubble count — used for dedup
        savedAt: Date.now(),
      }));
    } catch (e) { /* quota exceeded — silently ignore */ }
  },

  clear() {
    localStorage.removeItem(LS_KEY);
  },

  /**
   * On page load: restore a saved session if < 2 hours old.
   * First validates the session exists on the server — if the backend was
   * restarted, the session_id is stale and we clear it without an error banner.
   */
  async restore() {
    let saved;
    try { saved = JSON.parse(localStorage.getItem(LS_KEY)); } catch { return false; }
    if (!saved || !saved.sessionId) return false;
    if (Date.now() - saved.savedAt > 2 * 60 * 60 * 1000) { this.clear(); return false; }

    // Ping the server to confirm this session still exists.
    // /raise-hand with an already-granted or AI-speaking session returns
    // a JSON body — any non-404 response means the session is alive.
    try {
      const res = await fetch(
        `${BASE_URL}/raise-hand?session_id=${encodeURIComponent(saved.sessionId)}`,
        { method: 'POST' }
      );
      if (res.status === 404) {
        // Session not on server (backend restarted) — silently clear and start fresh
        this.clear();
        return false;
      }
    } catch {
      // Network error — backend is down; don't restore
      this.clear();
      return false;
    }

    // Session confirmed alive — restore UI
    state.sessionId = saved.sessionId;
    state.isActive = true;
    state.isEnded = false;
    state.turnCount = saved.turnCount || 0;
    state.restoredMsgCount = saved.lastMsgCount || 0;

    // Restore sidebar
    document.getElementById('session-setup').classList.add('hidden');
    document.getElementById('session-status').classList.remove('hidden');
    document.getElementById('session-badge').classList.remove('hidden');
    document.getElementById('status-topic').textContent = saved.topic || '';
    document.getElementById('turn-counter').textContent = state.turnCount;

    // Restore transcript
    const transcript = document.getElementById('transcript');
    transcript.innerHTML = saved.transcriptHtml || '';
    document.getElementById('empty-state').classList.add('hidden');
    transcript.scrollTop = transcript.scrollHeight;

    // Restart countdown timer from saved seconds (0 → trigger end immediately)
    const remaining = (saved.remainingTime > 0) ? saved.remainingTime : 30;
    sessionTimer.start(remaining);

    // Floor state MUST be set before silenceTimer.reset() checks it
    ui.setFloor('WAITING_FOR_HAND');
    silenceTimer.reset();

    return true;
  },
};


/* =========================================================
   UI
   ========================================================= */
const ui = {
  els: {
    errorBanner: document.getElementById('error-banner'),
    errorText: document.getElementById('error-text'),
    errorClose: document.getElementById('error-close'),
    startBtn: document.getElementById('start-btn'),
    topicInput: document.getElementById('topic-input'),
    durationInput: document.getElementById('duration-input'),
    sessionSetup: document.getElementById('session-setup'),
    sessionStatus: document.getElementById('session-status'),
    statusTopic: document.getElementById('status-topic'),
    timerDisplay: document.getElementById('timer-display'),
    turnCounter: document.getElementById('turn-counter'),
    endBtn: document.getElementById('end-btn'),
    transcript: document.getElementById('transcript'),
    emptyState: document.getElementById('empty-state'),
    loadingBar: document.getElementById('loading-bar'),
    loadingText: document.getElementById('loading-text'),
    sessionBadge: document.getElementById('session-badge'),
    evalPanel: document.getElementById('eval-panel'),
    evalLoading: document.getElementById('eval-loading'),
    evalContent: document.getElementById('eval-content'),
    evalClose: document.getElementById('eval-close'),
    floorInactive: document.getElementById('floor-inactive'),
    floorIdle: document.getElementById('floor-idle'),
    floorQueued: document.getElementById('floor-queued'),
    floorGranted: document.getElementById('floor-granted'),
    raiseHandBtn: document.getElementById('raise-hand-btn'),
    messageInput: document.getElementById('message-input'),
    sendBtn: document.getElementById('send-btn'),
  },

  _errorTimer: null,
  showError(msg) {
    this.els.errorText.textContent = msg;
    this.els.errorBanner.classList.remove('hidden');
    clearTimeout(this._errorTimer);
    this._errorTimer = setTimeout(() => this.hideError(), 8000);
  },
  hideError() { this.els.errorBanner.classList.add('hidden'); },

  /* ---------- 4-state floor machine ---------- */
  /**
   * Transitions the floor UI to match the current uiState.
   * Hand raise button: visible in AI_SPEAKING + WAITING_FOR_HAND
   * Text input: ONLY visible in USER_SPEAKING
   */
  setFloor(uiState) {
    console.log("STATE_CHANGE", state.uiState, uiState);
    state.uiState = uiState;
    const { floorInactive, floorIdle, floorQueued, floorGranted, raiseHandBtn } = this.els;

    floorInactive.classList.add('hidden');
    floorIdle.classList.add('hidden');
    floorQueued.classList.add('hidden');
    floorGranted.classList.add('hidden');

    switch (uiState) {
      case 'INACTIVE':
      case 'ENDED':
        floorInactive.classList.remove('hidden');
        raiseHandBtn.disabled = true;
        break;

      case 'AI_SPEAKING':
        // Hand raise visible & enabled, text hidden
        floorIdle.classList.remove('hidden');
        raiseHandBtn.disabled = false;
        break;

      case 'WAITING_FOR_HAND':
      case 'AI_TURN_ASSIGNED':
        // Hand raise visible & enabled, text hidden, silence timer will fire
        floorIdle.classList.remove('hidden');
        raiseHandBtn.disabled = false;
        break;

      case 'QUEUED':
        // Hand raised, waiting for AI to finish
        floorQueued.classList.remove('hidden');
        raiseHandBtn.disabled = true;
        break;

      case 'USER_SPEAKING':
        // Text input visible, raise hand hidden
        floorGranted.classList.remove('hidden');
        raiseHandBtn.disabled = true;
        requestAnimationFrame(() => this.els.messageInput.focus());
        break;
    }
  },

  /* ---------- loading bar ---------- */
  setLoading(active, text = '') {
    if (active) {
      this.els.loadingBar.classList.remove('hidden');
      this.els.loadingText.textContent = text;
    } else {
      this.els.loadingBar.classList.add('hidden');
    }
  },

  /* ---------- session lifecycle ---------- */
  onSessionStarted(topic) {
    this.els.sessionSetup.classList.add('hidden');
    this.els.sessionStatus.classList.remove('hidden');
    this.els.statusTopic.textContent = topic;
    this.els.sessionBadge.classList.remove('hidden');
    this.els.emptyState.classList.add('hidden');
    this.setFloor('AI_SPEAKING');  // Initial state: moderator intro counts as AI_SPEAKING phase
  },

  onSessionEnded() {
    silenceTimer.cancel();
    sessionTimer.stop();
    this.els.endBtn.disabled = true;
    this.setFloor('ENDED');
    this.els.evalPanel.classList.remove('hidden');
  },

  updateTimer(s) {
    const mm = Math.floor(Math.max(0, s) / 60).toString().padStart(2, '0');
    const ss = Math.max(0, s % 60).toString().padStart(2, '0');
    this.els.timerDisplay.textContent = `${mm}:${ss}`;
    this.els.timerDisplay.classList.toggle('warning', s <= 15);
  },

  incrementTurn() {
    state.turnCount += 1;
    this.els.turnCounter.textContent = state.turnCount;
  },

  /* ---------- messages ---------- */
  _classify(s) {
    const sl = s.toLowerCase();
    if (sl === 'user') return 'user';
    if (sl === 'moderator') return 'moderator';
    return 'ai';
  },
  _label(s, cls) {
    if (cls === 'user') return 'You';
    if (cls === 'moderator') return 'Moderator';
    return s.replace(/([a-z])(\d+)/gi, '$1 $2').replace(/\b\w/g, c => c.toUpperCase());
  },
  _avatar(s, cls) {
    if (cls === 'user') return 'ME';
    if (cls === 'moderator') return 'MOD';
    const m = s.match(/\d+/); return m ? `P${m[0]}` : 'AI';
  },
  _escape(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  },

  appendMessage(speaker, text) {
    // Dedup guard: after a page restore, the transcript HTML already contains
    // the prior bubbles. The first N appendMessage calls (N = restoredMsgCount)
    // are redundant re-appends — skip them to prevent duplicate messages.
    if (state.restoredMsgCount > 0) {
      state.restoredMsgCount -= 1;
      return null;
    }

    this.els.emptyState.classList.add('hidden');
    const cls = this._classify(speaker);
    const label = this._label(speaker, cls);
    const ava = this._avatar(speaker, cls);
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const el = document.createElement('div');
    el.className = `message ${cls}`;
    el.innerHTML = `
      <div class="message-meta">
        <span class="message-avatar">${ava}</span>
        <span class="message-speaker">${label}</span>
      </div>
      <div class="bubble">${this._escape(text)}</div>
      <time class="message-time">${time}</time>
    `;
    this.els.transcript.appendChild(el);
    this._scroll();
    persist.save();   // auto-save after every new message
    return el;
  },

  /**
   * Creates an empty streaming bubble and returns the bubble text node
   * so tokens can be appended directly.
   */
  createStreamingBubble(speaker) {
    this.els.emptyState.classList.add('hidden');
    const cls = this._classify(speaker);
    const label = this._label(speaker, cls);
    const ava = this._avatar(speaker, cls);
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const el = document.createElement('div');
    el.className = `message ${cls} streaming`;
    el.innerHTML = `
      <div class="message-meta">
        <span class="message-avatar">${ava}</span>
        <span class="message-speaker">${label}</span>
      </div>
      <div class="bubble"><span class="stream-text"></span><span class="stream-cursor">▋</span></div>
      <time class="message-time">${time}</time>
    `;
    this.els.transcript.appendChild(el);
    this._scroll();
    return el.querySelector('.stream-text');
  },

  finalizeStreamingBubble(el) {
    // Remove the blinking cursor
    const cursor = el.closest('.message').querySelector('.stream-cursor');
    if (cursor) cursor.remove();
    const msgEl = el.closest('.message');
    if (msgEl) msgEl.classList.remove('streaming');
  },

  _scroll() {
    requestAnimationFrame(() => {
      this.els.transcript.scrollTop = this.els.transcript.scrollHeight;
    });
  },

  showEvalLoading() {
    this.els.evalLoading.classList.remove('hidden');
    this.els.evalContent.classList.add('hidden');
  },
  showEvalResult(text) {
    this.els.evalLoading.classList.add('hidden');
    this.els.evalContent.classList.remove('hidden');
    this.els.evalContent.textContent = text;
  },
};

/* =========================================================
   SHARED STREAMING CONSUMER
   Reads an NDJSON stream from api.aiSpeak() or api.speak(),
   renders tokens into a streaming bubble,
   then handles the final "done" chunk.
   Returns the "done" chunk object.
   ========================================================= */
async function consumeStream(streamGen, speakerHint) {
  // speakerHint used before we know the real participant name
  // First token reveals the name — handled lazily via createStreamingBubble on first token

  let streamTextEl = null;
  let fullText = '';
  let doneChunk = null;

  for await (const chunk of streamGen) {
    if (chunk.type === 'token') {
      if (!streamTextEl) {
        // We only know the real speaker name in the "done" chunk,
        // but we need to create the bubble now. Use speakerHint for avatar.
        streamTextEl = ui.createStreamingBubble(speakerHint || 'ai');
      }
      streamTextEl.textContent += chunk.text;
      fullText += chunk.text;
      ui._scroll();
    } else if (chunk.type === 'done') {
      doneChunk = chunk;
    }
  }

  if (streamTextEl) ui.finalizeStreamingBubble(streamTextEl);
  return doneChunk;
}

/* =========================================================
   HANDLERS
   ========================================================= */
const handlers = {

  async startSession() {
    const topic = ui.els.topicInput.value.trim();
    const duration = parseInt(ui.els.durationInput.value, 10);
    if (!topic) { ui.showError('Please enter a discussion topic.'); return; }
    if (!duration || duration < 10) { ui.showError('Duration must be at least 10 seconds.'); return; }

    ui.els.startBtn.disabled = true;
    ui.setLoading(true, 'Starting session…');
    try {
      const data = await api.start(topic, duration);
      state.sessionId = data.session_id;
      state.isActive = true;
      ui.onSessionStarted(topic);
      ui.appendMessage('moderator', data.message);
      sessionTimer.start(duration);
      // After intro, transition to AI_TURN_ASSIGNED and start silence clock
      ui.setFloor('AI_TURN_ASSIGNED');
      silenceTimer.reset();
    } catch (err) {
      ui.showError(`Could not start session: ${err.message}`);
      ui.els.startBtn.disabled = false;
    } finally {
      ui.setLoading(false);
    }
  },

  async raiseHand() {
    if (!state.isActive || state.isEnded) return;
    if (!['AI_SPEAKING', 'WAITING_FOR_HAND'].includes(state.uiState)) return;

    // ── CRITICAL: never make an HTTP request while a stream is open. ──────────
    // The concurrent fetch can corrupt the active chunked transfer on the
    // same local server (Uvicorn single-worker). Instead, record the intent
    // locally and fire the real request once the stream finishes.
    if (state.streamActive) {
      state.handRaisedPending = true;
      ui.setFloor('QUEUED');   // immediate visual feedback, no HTTP
      return;
    }

    silenceTimer.cancel();
    ui.setLoading(true, 'Requesting the floor…');
    try {
      const data = await api.raiseHand(state.sessionId);
      if (data.status === 'granted') {
        ui.appendMessage('moderator', data.moderator_message);
        ui.setFloor('USER_SPEAKING');
      } else if (data.status === 'queued') {
        ui.setFloor('QUEUED');
      } else if (data.status === 'already_granted') {
        ui.setFloor('USER_SPEAKING');
      }
    } catch (err) {
      const msg = err.message || '';
      // 404 = session gone — treat as fatal, stop the discussion
      if (msg.includes('404') || msg.includes('Session not found')) {
        state.isActive = false;
        state.isEnded = true;
        state.handRaisedPending = false;
        persist.clear();
        ui.setFloor('ENDED');
        ui.showError('Session not found on server. Please start a new session.');
        return;
      }
      ui.showError(`Hand raise failed: ${msg}`);
      ui.setFloor('WAITING_FOR_HAND');
      silenceTimer.reset();
    } finally {
      ui.setLoading(false);
    }
  },

  async sendMessage() {
    if (state.uiState !== 'USER_SPEAKING') return;
    if (state.streamActive) return;
    const message = ui.els.messageInput.value.trim();
    if (!message) return;

    ui.els.messageInput.value = '';
    autoResize(ui.els.messageInput);
    ui.appendMessage('user', message);
    ui.incrementTurn();
    silenceTimer.cancel();

    ui.setFloor('AI_SPEAKING');
    ui.setLoading(true, 'AI participant responding…');
    state.streamActive = true;

    try {
      const streamGen = api.speak(state.sessionId, message);
      const done = await consumeStream(streamGen, 'ai');
      if (done) {
        // Terminal-state guard: if session ended mid-stream, skip all
        // floor/silence logic and hand off to endSession.
        if (state.isEnded || state.pendingEnd) {
          state.streamActive = false;
          if (state.pendingEnd) { state.pendingEnd = false; handlers.endSession(true); }
          return;
        }
        ui.appendMessage('moderator', done.moderator_message);
        if (done.hand_queued_granted || state.handRaisedPending) {
          state.handRaisedPending = false;
          state.streamActive = false;
          ui.setFloor('WAITING_FOR_HAND');
          handlers.raiseHand();
          return;
        }
        state.streamActive = false;
        ui.setFloor('AI_TURN_ASSIGNED');
        silenceTimer.reset();
      }
    } catch (err) {
      if (!err.message.includes('403') && !state.isEnded) {
        ui.showError(`Stream interrupted: ${err.message}. Returning to discussion.`);
      }
      state.handRaisedPending = false;
      state.streamActive = false;
      if (state.pendingEnd) { state.pendingEnd = false; handlers.endSession(true); return; }
      if (!state.isEnded) { ui.setFloor('AI_TURN_ASSIGNED'); silenceTimer.reset(); }
    } finally {
      state.streamActive = false;  // idempotent safety net
      ui.setLoading(false);
    }
  },

  async aiSpeak() {
    console.log("AI_SPEAK_ENTER");
    if (state.uiState !== "AI_TURN_ASSIGNED") {
      console.log("aiSpeak blocked - invalid state:", state.uiState);
      return;
    }
    if (aiRequestInFlight) {
      console.log("aiSpeak blocked - request already in flight");
      return;
    }
    aiRequestInFlight = true;

    aiRequestCounter++;
    console.log("AI_REQUEST_ID", aiRequestCounter);
    // Hard terminal guards — checked before every attempt
    if (!state.isActive || state.isEnded) { aiRequestInFlight = false; return; }
    if (state.pendingEnd) { aiRequestInFlight = false; return; }          // session expiring; endSession() will fire when stream finishes
    if (state.uiState !== 'AI_TURN_ASSIGNED') { aiRequestInFlight = false; return; }
    if (state.streamActive) { aiRequestInFlight = false; return; }

    silenceTimer.cancel();
    ui.setFloor('AI_SPEAKING');
    ui.setLoading(true, 'AI participant speaking…');
    state.streamActive = true;

    try {
      const streamGen = api.aiSpeak(state.sessionId);
      const done = await consumeStream(streamGen, 'ai');
      if (done) {
        // Terminal-state guard: if session ended mid-stream, hand off to endSession.
        if (state.isEnded || state.pendingEnd) {
          state.streamActive = false;
          if (state.pendingEnd) { state.pendingEnd = false; handlers.endSession(true); }
          return;
        }
        ui.appendMessage('moderator', done.moderator_message);
        if (done.hand_queued_granted || state.handRaisedPending) {
          state.handRaisedPending = false;
          state.streamActive = false;
          ui.setFloor('WAITING_FOR_HAND');
          handlers.raiseHand();
          return;
        }
        state.streamActive = false;
        ui.setFloor('AI_TURN_ASSIGNED');
        if (!state.pendingEnd) silenceTimer.reset();
      }
    } catch (err) {
      const msg = err.message || '';

      // ── FATAL: 404 or 410 — session gone or expired ─────────────────────
      // 404 = session never existed / backend restarted
      // 410 = session.is_ended = True on backend, or is_time_over()
      // Both are unrecoverable — stop all timers and show terminal state.
      if (msg.includes('404') || msg.includes('410') ||
        msg.includes('Session not found') || msg.includes('Session has ended') ||
        msg.includes('expired')) {
        silenceTimer.cancel();
        state.uiState = 'ENDED';
        state.isEnded = true;
        state.isActive = false;
        state.pendingEnd = false;
        state.handRaisedPending = false;
        persist.clear();
        ui.setFloor('ENDED');
        // Only show an error banner if this was unexpected (not a normal auto-end)
        if (msg.includes('410')) console.log("SESSION_GONE_STOPPING_TIMERS");
        if (!msg.includes('410') && !msg.includes('expired')) {
          ui.showError(
            msg.includes('Not Found') && !msg.includes('Session')
              ? 'Could not reach /ai-speak. Restart the backend server.'
              : 'Session not found. Backend was likely restarted — please start a new session.'
          );
        }
        return;
      }

      // ── BENIGN: 409 conflict ──────────────────────────────────────────
      // Release streamActive here (finally will also set it, idempotent).
      // Without this, silenceTimer.reset() sees streamActive=true and exits early,
      // then finally sets it false, leaving the session stuck with no silence timer.
      if (msg.includes('409') || msg.includes('floor') || msg.includes('speaking') || msg.includes('Conflict')) {
        state.streamActive = false;
        if (!state.isEnded && !state.pendingEnd) {
          ui.setFloor('AI_TURN_ASSIGNED');
          // Brief delay so finally has time to run before the next timer tick
          setTimeout(() => silenceTimer.reset(), 50);
        }
        return;
      }

      // ── Network / stream interruption ─────────────────────────────────
      state.handRaisedPending = false;
      state.streamActive = false;
      if (state.pendingEnd) { state.pendingEnd = false; handlers.endSession(true); return; }
      if (!state.isEnded) {
        ui.showError(`AI response error: ${msg}`);
        ui.setFloor('AI_TURN_ASSIGNED');
        silenceTimer.reset();
      }
    } finally {
      aiRequestInFlight = false;
      state.streamActive = false;
      ui.setLoading(false);
    }
  },



  async endSession(auto = false) {
    if (!state.isActive || state.isEnded) return;
    state.isActive = false;   // blocks any new stream from starting
    state.isEnded = true;
    silenceTimer.cancel();
    persist.clear();

    ui.onSessionEnded();
    ui.showEvalLoading();
    ui.appendMessage('moderator', auto
      ? 'Time is up! The discussion has ended. Generating your evaluation…'
      : 'The discussion has ended. Generating your evaluation…');

    // Wait for any active AI stream to finish on its own before calling /end.
    // When state.isEnded = true above, the stream's catch handler returns to
    // WAITING_FOR_HAND then releases streamActive = false in its finally block.
    // We must wait for this cleanup so the backend's except block has time to
    // append the partial AI response to session.history BEFORE evaluate_user()
    // reads it. Without this wait, evaluation receives an incomplete transcript.
    // (The backend /end also polls ai_is_speaking as a secondary safety net.)
    if (state.streamActive) {
      await new Promise(resolve => {
        const check = setInterval(() => {
          if (!state.streamActive) { clearInterval(check); resolve(); }
        }, 200);
        // Hard timeout — don't block evaluation forever if stream is stuck
        setTimeout(() => { clearInterval(check); resolve(); }, 8000);
      });
    }

    try {
      const data = await api.end(state.sessionId);
      ui.showEvalResult(data.evaluation);
    } catch (err) {
      ui.showEvalResult(`⚠️ Evaluation unavailable.\n\n${err.message}`);
    }
  },

};

/* =========================================================
   TEXTAREA AUTO-RESIZE
   ========================================================= */
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

/* =========================================================
   EVENT BINDINGS
   ========================================================= */
function bindEvents() {
  const { els } = ui;
  els.startBtn.addEventListener('click', handlers.startSession);
  els.endBtn.addEventListener('click', () => handlers.endSession(false));
  els.raiseHandBtn.addEventListener('click', handlers.raiseHand);
  els.sendBtn.addEventListener('click', handlers.sendMessage);
  els.errorClose.addEventListener('click', () => ui.hideError());
  els.evalClose.addEventListener('click', () => els.evalPanel.classList.add('hidden'));

  els.messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handlers.sendMessage(); }
  });
  els.messageInput.addEventListener('input', () => autoResize(els.messageInput));
  els.topicInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') handlers.startSession();
  });
}

/* =========================================================
   INIT
   ========================================================= */
(async function init() {
  bindEvents();
  // Validate saved session against server before restoring.
  // persist.restore() is async — it pings /raise-hand to confirm the
  // session still exists. If the backend was restarted, it returns false
  // and clears localStorage silently, showing the normal start screen.
  const restored = await persist.restore();
  if (!restored) {
    ui.setFloor('INACTIVE');
  }
})();

