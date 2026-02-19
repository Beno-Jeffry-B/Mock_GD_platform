from app.core.ollama_client import call_model


def evaluate_user(topic, history):

    prompt = f"""
You are a strict GD evaluator.

Topic: {topic}

Full discussion transcript:
{history}

Evaluate ONLY the user performance on:
Clarity /10
Leadership /10
Rebuttal Skill /10
Tone /10
Grammar /10

Provide detailed feedback.
"""

    return call_model(prompt, max_tokens=500)
