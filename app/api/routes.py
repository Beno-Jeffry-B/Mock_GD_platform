from fastapi import APIRouter
import uuid

from app.storage.memory_store import create_session, get_session
from app.services.moderator import generate_intro
from app.services.turn_manager import handle_user_turn
from app.services.evaluator import evaluate_user

router = APIRouter()


@router.post("/start")
def start(topic: str, duration: int):

    session_id = str(uuid.uuid4())

    create_session(session_id, topic, duration)

    intro = generate_intro(topic)

    session = get_session(session_id)
    session.history.append(("moderator", intro))

    return {"session_id": session_id, "message": intro}


@router.post("/speak")
def speak(session_id: str, message: str):

    session = get_session(session_id)

    name, response = handle_user_turn(session, message)

    return {"speaker": name, "response": response}


@router.post("/end")
def end(session_id: str):

    session = get_session(session_id)

    evaluation = evaluate_user(session.topic, session.history)

    return {"evaluation": evaluation}


from app.services.turn_manager import (
    handle_user_turn,
    raise_hand,
    check_and_progress
)

@router.post("/raise-hand")
def raise_user_hand(session_id: str):

    session = get_session(session_id)

    raise_hand(session)

    return {"status": "Hand raised"}


@router.post("/progress")
def progress(session_id: str):

    session = get_session(session_id)

    speaker, message = check_and_progress(session)

    if message == "TIME_OVER":
        return {"status": "time_over"}

    if speaker:
        return {
            "speaker": speaker,
            "message": message
        }

    return {"status": "waiting"}
