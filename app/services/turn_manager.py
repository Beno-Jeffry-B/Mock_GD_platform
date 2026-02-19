import random
from app.services.participants import generate_participant_response


def format_history(history):
    """
    Converts internal history list into clean transcript string.
    Prevents model confusion from raw Python tuples.
    """
    formatted = ""

    for speaker, text in history:
        formatted += f"{speaker.upper()}: {text.strip()}\n\n"

    return formatted.strip()


def handle_user_turn(session, message):
    """
    Handles a user speaking turn:
    1. Appends user message
    2. Randomly selects a participant
    3. Generates participant response
    4. Appends response to history
    """

    # Safety: check if session time is over
    if session.is_time_over():
        return "system", "Session time is over. Please end the discussion."

    # Add user message to history
    session.history.append(("user", message.strip()))

    # Format clean transcript
    formatted_history = format_history(session.history)

    # Generate participant response
    name, response = generate_participant_response(
        topic=session.topic, history=formatted_history
    )

    # Clean response
    response = response.strip()

    # Append participant response
    session.history.append((name, response))

    return name, response
