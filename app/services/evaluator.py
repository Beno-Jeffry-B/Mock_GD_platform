from app.core.ollama_client import call_model

_FALLBACK = (
    "Evaluation could not be generated (Ollama did not respond in time). "
    "The discussion history was recorded correctly. "
    "Please re-run the session and try again."
)

# Cap how many history turns are sent to the evaluator.
# A long session can produce 20+ turns × 100 tokens each = 2000+ tokens of input,
# which pushes total prompt well past what a 7B model handles quickly.
# Keeping the last 12 turns (~600 tokens of context) is enough for scoring.
_MAX_HISTORY_TURNS = 12


def evaluate_user(topic, history):
    if not history:
        return (
            "No discussion history found. "
            "If the user did not speak, scores should reflect zero participation:\n"
            "Clarity: 0/10 — no contribution.\n"
            "Leadership: 0/10 — no contribution.\n"
            "Rebuttal Skill: 0/10 — no contribution.\n"
            "Tone: N/A — no contribution.\n"
            "Grammar: N/A — no contribution."
        )

    # Check if user ever spoke at all
    user_spoke = any(speaker == "user" for speaker, _ in history)

    # Trim to last N turns to keep prompt size manageable
    trimmed = history[-_MAX_HISTORY_TURNS:]
    lines = []
    for speaker, text in trimmed:
        tag = "User" if speaker == "user" else speaker.capitalize()
        lines.append(f"{tag}: {text}")
    transcript = "\n".join(lines)

    if len(history) > _MAX_HISTORY_TURNS:
        context_note = f"(Showing last {_MAX_HISTORY_TURNS} of {len(history)} turns)"
    else:
        context_note = ""

    silence_note = (
        "\nNOTE: The user did not speak at all during this discussion. "
        "Score Clarity, Leadership, and Rebuttal Skill as 0/10.\n"
        if not user_spoke else ""
    )

    prompt = f"""You are a strict Group Discussion evaluator.

Topic: {topic}
{context_note}

Discussion transcript:
{transcript}
{silence_note}
Score ONLY the user's performance. Give a number /10 for each, then one sentence of feedback:

Clarity /10:
Leadership /10:
Rebuttal Skill /10:
Tone /10:
Grammar /10:

Overall summary (2 sentences max):
"""
    try:
        # Use a longer timeout for evaluation — 500-token output at ~10 tok/s = ~50s.
        # Set 180s to give ample headroom on slow local hardware.
        # max_tokens reduced to 350 — structured scored output doesn't need 500 tokens.
        return call_model(prompt, max_tokens=350, timeout=180)
    except Exception as exc:
        return f"{_FALLBACK}\n\n(Error: {exc})"
