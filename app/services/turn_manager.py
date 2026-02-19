import random
from app.services.participants import generate_participant_response
from app.services.moderator import generate_intro
from app.services.evaluator import evaluate_user


def format_history(history):
    formatted = ""
    for speaker, text in history:
        formatted += f"{speaker.upper()}: {text.strip()}\n\n"
    return formatted.strip()


def raise_hand(session, user_name="user"):
    """
    Adds user to speaking queue
    """
    if user_name not in session.hand_raise_queue:
        session.hand_raise_queue.append(user_name)


def handle_user_turn(session, message):
    """
    User speaks after moderator allows.
    """

    if session.is_time_over():
        return "system", "Session time is over."

    session.history.append(("user", message.strip()))
    session.last_activity_time = session.start_time = session.start_time

    formatted_history = format_history(session.history)

    name, response = generate_participant_response(
        topic=session.topic, history=formatted_history
    )

    session.history.append((name, response))
    session.last_activity_time = session.start_time = session.start_time
    session.turn_count += 1

    return name, response


def auto_participant_turn(session):
    """
    Triggered when silence timeout occurs.
    Random participant speaks.
    """

    formatted_history = format_history(session.history)

    name, response = generate_participant_response(
        topic=session.topic, history=formatted_history
    )

    session.history.append((name, response))
    session.last_activity_time = session.start_time = session.start_time
    session.turn_count += 1

    return name, response


def moderator_allocate_turn(session):
    """
    Moderator checks hand raise queue.
    """

    if session.hand_raise_queue:
        next_speaker = session.hand_raise_queue.popleft()

        moderator_message = f"{next_speaker.upper()}, you may speak now."

        session.history.append(("moderator", moderator_message))
        session.current_speaker = next_speaker
        session.last_activity_time = session.start_time = session.start_time

        return "moderator", moderator_message

    return None, None


def check_and_progress(session):
    """
    Core turn engine logic.
    Call this periodically (UI polling or WebSocket loop).
    """

    if session.is_time_over():
        return "system", "TIME_OVER"

    # If someone raised hand
    speaker, msg = moderator_allocate_turn(session)
    if speaker:
        return speaker, msg

    # Silence auto-trigger
    if session.is_silence_timeout():
        return auto_participant_turn(session)

    return None, None
