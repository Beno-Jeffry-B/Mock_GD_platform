import random
from app.core.ollama_client import call_model, call_model_stream

PERSONALITIES = {
    "participant1": "Analytical, calm, logical thinker who builds arguments with evidence.",
    "participant2": "Challenging, critical, assertive debater who questions assumptions.",
    "participant3": "Balanced, supportive speaker who synthesises viewpoints and finds common ground.",
}

# Keys list kept stable for round-robin indexing
_NAMES = list(PERSONALITIES.keys())
_last_index: int = -1   # module-level; persists for the lifetime of the server process


def _pick_next_participant() -> str:
    """
    Round-robin selection: cycles through participant1 → participant2 → participant3
    and repeats. Never picks the same participant twice in a row.
    Module-level state is fine for a local single-session simulator.
    """
    global _last_index
    _last_index = (_last_index + 1) % len(_NAMES)
    return _NAMES[_last_index]


def _build_prompt(name: str, topic: str, history: list) -> str:
    """Build a single-participant response prompt.
    Formats history as readable dialogue to prevent raw Python repr leaking
    into the prompt (which inflates length and confuses the model).
    Explicitly prevents multi-persona output within a single response.
    """
    persona = PERSONALITIES[name]
    lines = []
    for speaker, text in history:
        tag = "User" if speaker == "user" else speaker.capitalize()
        lines.append(f"{tag}: {text}")
    dialogue = "\n".join(lines) if lines else "(discussion just started)"

    return f"""You are {name}, one participant in a group discussion.
Personality: {persona}

Topic: {topic}

Discussion so far:
{dialogue}

Instructions:
- Write ONLY your single response as {name}.
- Do NOT write dialogue for other participants.
- Do NOT prefix your response with your name or any label.
- Respond in 2-3 sentences only.
- Stay in character. Add a new point not already made.
"""



def generate_participant_response(topic: str, history: list) -> tuple:
    """Blocking — returns (name, full_response_string)."""
    name = _pick_next_participant()
    response = call_model(_build_prompt(name, topic, history))
    return name, response


def generate_participant_response_stream(topic: str, history: list) -> tuple:
    """
    Streaming — returns (name, token_generator).
    Caller must consume the generator and assemble the full response.
    """
    name = _pick_next_participant()
    return name, call_model_stream(_build_prompt(name, topic, history))
