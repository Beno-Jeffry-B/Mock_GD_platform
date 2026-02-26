import random
from app.core.ollama_client import call_model


# Canned moderator transition lines — no LLM call needed.
_TRANSITION_LINES = [
    "Thank you. The floor is open — please raise your hand to speak.",
    "Noted. Anyone else? Raise your hand if you'd like to contribute.",
    "Good point. The discussion continues — hand raised speakers will be recognised.",
    "Interesting. Who else would like to weigh in? Raise your hand.",
    "The floor is open. Raise your hand to take a turn.",
]

# Canned floor-grant lines — replaces LLM call inside the streaming generator.
# CRITICAL: moderator_grant_turn is called FROM WITHIN _stream_ai_response's
# generator body. If it makes a second call_model() (Ollama HTTP request) while
# the streaming Ollama connection is still technically open, Ollama gets two
# concurrent requests and fails the second one → ERR_INCOMPLETE_CHUNKED_ENCODING.
# Canned messages eliminate this second Ollama call entirely.
_GRANT_LINES = [
    "You may speak now — the floor is yours.",
    "Go ahead, the floor is yours.",
    "You have the floor. Please proceed.",
    "You may take the floor now.",
    "The floor is yours — please go ahead.",
]


_CANNED_INTRO = (
    "Welcome to today's Group Discussion. "
    "Please keep your contributions concise and on-topic. "
    "To speak, raise your hand and wait for permission. "
    "Let's begin — the floor is now open."
)


def generate_intro(topic: str) -> str:
    """LLM-generated opening. Falls back to a canned intro if Ollama is slow or unreachable."""
    prompt = f"""
You are a professional Group Discussion Moderator.

Topic: {topic}

Introduce the discussion in under 80 words.
State the topic. Explain that participants must raise their hand and wait for permission before speaking.
"""
    try:
        return call_model(prompt, max_tokens=150)
    except Exception:
        # Ollama timeout, connection refused, or any other error — use canned line
        # so /start never returns 500.
        return f"Welcome. Today's topic is: {topic}. {_CANNED_INTRO}"


def moderator_grant_turn(session) -> str:
    """
    Grants the floor to the user.
    This is the ONLY place that sets user_turn_granted = True.

    Uses canned messages instead of a live LLM call so it is safe to call
    from inside a streaming generator without opening a second Ollama connection.
    """
    message = random.choice(_GRANT_LINES)
    session.add_message("moderator", message)
    session.user_turn_granted = True
    session.hand_raised = False
    session.hand_queue = False
    session.current_speaker = "user"
    session.save()
    return message


def moderator_transition(session) -> str:
    """
    Called after EVERY AI participant turn.
    - If user hand is queued → grant floor (canned, no LLM call).
    - Otherwise → canned neutral transition.
    Silence timer starts on frontend after this message is received.
    """
    if session.hand_queue:
        return moderator_grant_turn(session)

    msg = random.choice(_TRANSITION_LINES)
    session.add_message("moderator", msg)
    session.current_speaker = "ai"
    session.save()
    return msg
