import requests
from app.core.config import MODEL_NAME, OLLAMA_URL


def call_model(prompt: str, max_tokens: int = 300):

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }

    response = requests.post(OLLAMA_URL, json=payload)
    return response.json().get("response", "")
