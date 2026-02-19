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
