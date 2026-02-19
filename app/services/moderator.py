from app.core.ollama_client import call_model


def generate_intro(topic: str):
    prompt = f"""
You are a professional Group Discussion Moderator.

Topic: {topic}

Introduce the discussion.
Explain rules briefly.
Keep under 150 words.
"""
    return call_model(prompt)
