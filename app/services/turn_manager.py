import json
from fastapi import HTTPException
from app.services.participants import generate_participant_response_stream
from app.services.moderator import moderator_grant_turn, moderator_transition


def _stream_ai_response(session):
    """
    Shared generator for /speak and /ai-speak.
    Streams Ollama tokens as NDJSON, then emits a final "done" line.

    IMPORTANT: uses try/finally so session.ai_is_speaking is ALWAYS reset
    to False — even if Ollama errors mid-stream or the client disconnects.
    Without this, a crashed stream leaves ai_is_speaking = True permanently,
    causing every subsequent /ai-speak call to return 409.
    """
    session.ai_is_speaking = True
    session.save()
    name, token_gen = generate_participant_response_stream(session.topic, session.history)
    parts = []

    try:
        for token in token_gen:
            print("AI_STREAM_TOKEN")
            # If the session was ended mid-stream (frontend timer expired),
            # stop producing tokens immediately. Saving partial response below.
            if session.is_ended:
                break
            parts.append(token)
            yield json.dumps({"type": "token", "text": token}) + "\n"

        # ── Stream finished cleanly (or stopped due to session.is_ended) ─────
        print("AI_STREAM_END")
        full_response = "".join(parts)
        if full_response:
            session.add_message(name, full_response)
        session.reset_activity_clock()
        session.ai_is_speaking = False
        session.save()

        if session.is_ended:
            # Session ended mid-stream — close without moderator transition.
            # History is saved above; /end will evaluate after this returns.
            return

        mod_msg = moderator_transition(session)

        yield json.dumps({
            "type": "done",
            "speaker": name,
            "moderator_message": mod_msg,
            "hand_queued_granted": session.user_turn_granted,
        }) + "\n"

    except Exception:
        # Ollama error / client disconnect: save whatever we got, then re-raise
        # so the HTTP layer closes the stream with an incomplete body.
        # The frontend ERR_INCOMPLETE_CHUNKED_ENCODING catch will handle recovery.
        if parts:
            session.add_message(name, "".join(parts) + " [interrupted]")
        session.reset_activity_clock()
        raise

    finally:
        # Unconditional reset — this runs even if raise above triggers.
        session.ai_is_speaking = False
        session.save()


def handle_user_turn(session, message: str):
    """
    Validates floor ownership, appends user message, resets floor state,
    returns the streaming generator for the AI response that follows.
    Raises HTTPException(403) if user does not have the floor.
    """
    if session.is_ended:
        raise HTTPException(status_code=410, detail="Session has ended.")
    if not session.user_turn_granted:
        raise HTTPException(
            status_code=403,
            detail="You have not been granted the floor. Please raise your hand first."
        )

    # Record user message and revoke floor before streaming starts
    session.add_message("user", message)
    session.user_turn_granted = False
    session.hand_raised = False
    session.current_speaker = "ai"
    session.save()

    return _stream_ai_response(session)


def handle_ai_turn(session):
    """
    Guards for silence-triggered AI turn, returns the streaming generator.
    """
    # is_ended is set by /end — always check first so 410 fires even if
    # the countdown clock still has seconds remaining (frontend/backend skew).
    if session.is_ended:
        raise HTTPException(status_code=410, detail="Session has ended.")
    if session.user_turn_granted:
        raise HTTPException(status_code=409, detail="User currently has the floor.")
    if session.ai_is_speaking:
        raise HTTPException(status_code=409, detail="An AI participant is already speaking.")
    if session.is_time_over():
        print("TIMEOUT_TRIGGERED")
        raise HTTPException(status_code=410, detail="Session time has expired.")

    print("SILENCE_TRIGGERED")
    return _stream_ai_response(session)
