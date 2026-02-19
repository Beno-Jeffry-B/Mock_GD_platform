from app.models.session import Session

sessions = {}


def create_session(session_id: str, topic: str, duration: int):
    sessions[session_id] = Session(topic, duration)


def get_session(session_id: str):
    return sessions.get(session_id)


def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
