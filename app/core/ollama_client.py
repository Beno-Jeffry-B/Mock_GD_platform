import json
import requests
from app.core.config import MODEL_NAME, OLLAMA_URL


def call_model(prompt: str, max_tokens: int = 300, timeout: int = 60) -> str:
    """Blocking call — returns full response string."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json().get("response", "")


def call_model_stream(prompt: str, max_tokens: int = 300):
    """
    Generator that yields response text tokens one at a time.

    KEY FIX: Does NOT use 'with' context manager.
    The 'with' pattern suspends the open TCP connection to Ollama inside the
    generator frame between yields. If anything else calls Ollama (e.g.
    moderator_grant_turn) while this generator is still alive, Ollama receives
    two concurrent requests and fails the second one mid-stream, causing
    ERR_INCOMPLETE_CHUNKED_ENCODING.

    Instead: open the response, stream all lines, then call res.close()
    explicitly the moment we receive done=True. This releases the Ollama
    connection immediately, before control returns to _stream_ai_response.
    """
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }
    res = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=60)
    res.raise_for_status()
    try:
        for line in res.iter_lines():
            if line:
                chunk = json.loads(line)
                token = chunk.get("response", "")
                if token:
                    yield token
                if chunk.get("done", False):
                    break
    finally:
        # Always close the Ollama TCP connection before the caller continues.
        # This ensures Ollama is free to accept the next request
        # (moderator_grant_turn, or the next /speak call).
        res.close()
