import random
from app.core.ollama_client import call_model

PERSONALITIES = {
    "participant1": "Analytical, calm, logical thinker.",
    "participant2": "Challenging, critical, assertive debater.",
    "participant3": "Balanced, supportive, collaborative speaker.",
}


def generate_participant_response(topic, history):

    name = random.choice(list(PERSONALITIES.keys()))
    persona = PERSONALITIES[name]

    prompt = f"""
You are {name}.
Personality: {persona}

Topic: {topic}

Conversation so far:
{history}

Respond naturally in 3-4 lines.
"""

    response = call_model(prompt)

    return name, response
