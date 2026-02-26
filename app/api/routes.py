from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import uuid

from app.storage.memory_store import create_session, get_session
from app.services.moderator import generate_intro, moderator_grant_turn
from app.services.turn_manager import handle_user_turn, handle_ai_turn
from app.services.evaluator import evaluate_user

router = APIRouter()


def _require_session(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------
@router.post("/start")
def start(topic: str, duration: int):
    session_id = str(uuid.uuid4())
    create_session(session_id, topic, duration)
    intro = generate_intro(topic)
    session = get_session(session_id)
    session.add_message("moderator", intro)
    session.reset_activity_clock()
    return {"session_id": session_id, "message": intro}


# ---------------------------------------------------------------------------
# POST /raise-hand
# ---------------------------------------------------------------------------
@router.post("/raise-hand")
def raise_hand(session_id: str):
    session = _require_session(session_id)

    if session.user_turn_granted:
        return {"status": "already_granted", "moderator_message": None}

    if session.ai_is_speaking:
        session.hand_queue = True
        return {"status": "queued", "moderator_message": None}

    session.hand_raised = True
    moderator_message = moderator_grant_turn(session)
    return {"status": "granted", "moderator_message": moderator_message}


# ---------------------------------------------------------------------------
# POST /speak  → StreamingResponse (NDJSON)
# Guards are checked synchronously before the stream starts.
# ---------------------------------------------------------------------------
@router.post("/speak")
def speak(session_id: str, message: str):
    session = _require_session(session_id)
    # handle_user_turn raises 403 synchronously if floor not granted,
    # then returns the streaming generator.
    stream_gen = handle_user_turn(session, message)
    return StreamingResponse(stream_gen, media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# POST /ai-speak  → StreamingResponse (NDJSON)
# Called by the frontend silence timer.
# ---------------------------------------------------------------------------
@router.post("/ai-speak")
def ai_speak(session_id: str):
    import threading
    session = _require_session(session_id)
    print(f"[{threading.get_ident()}] AI_SPEAK_REQ: session_id={session_id} is_ended={session.is_ended} current_speaker={session.current_speaker} ai_is_speaking={session.ai_is_speaking}")
    print("AI_SPEAK_START", session_id)
    stream_gen = handle_ai_turn(session)
    return StreamingResponse(stream_gen, media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# POST /end
# ---------------------------------------------------------------------------
@router.post("/end")
def end(session_id: str):
    import time
    session = _require_session(session_id)

    # Signal the streaming generator to stop producing new tokens immediately.
    session.is_ended = True
    print("SESSION_MARKED_ENDED", session_id)
    session.save()

    # Wait for any in-flight stream to write its partial response to history
    # before evaluate_user() reads it. The generator checks session.is_ended
    # each iteration, breaks out, appends to history, then sets ai_is_speaking=False.
    deadline = time.time() + 8
    while session.ai_is_speaking and time.time() < deadline:
        time.sleep(0.15)

    evaluation = evaluate_user(session.topic, session.history)
    return {"evaluation": evaluation}
