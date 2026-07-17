"""Open-source model layer.

Two free providers, selected by the LLM_PROVIDER env var:

  - "ollama" (default): a model running locally via Ollama. Fully open source,
    no API key, no cost. Needs Ollama installed and a model pulled.
    https://ollama.com

  - "groq": open-source models (Llama, etc.) on Groq's free hosted API. Needs a
    free API key (GROQ_API_KEY) but no local compute — much faster.
    https://console.groq.com

Both return the same validated `Analysis` object, so nothing downstream cares
which one produced it.
"""

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from schema import (
    Analysis,
    JSON_INSTRUCTIONS,
    THREADS_JSON_INSTRUCTIONS,
    TOPICS_JSON_INSTRUCTIONS,
    Threads,
    Topics,
    analysis_schema,
    threads_schema,
    topics_schema,
)

# Load backend/.env so LLM_PROVIDER, GROQ_API_KEY, etc. are picked up
# automatically — no need to export env vars before running.
load_dotenv(Path(__file__).parent / ".env")

PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

# --- Ollama (local) -------------------------------------------------------
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# --- Groq (free hosted) ---------------------------------------------------
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")


class LLMError(RuntimeError):
    """Any failure talking to the model, normalized for the API layer."""


def analyze(system_prompt: str, note: str) -> Analysis:
    """Send the note to the configured provider and return a parsed Analysis."""
    raw = _complete(system_prompt + "\n\n" + JSON_INSTRUCTIONS, note,
                    analysis_schema(), num_predict=600)
    return _parse(raw, Analysis, "analysis")


def find_threads(system_prompt: str, digest: str) -> Threads:
    """Read back over many notes at once and name what keeps repeating."""
    raw = _complete(system_prompt + "\n\n" + THREADS_JSON_INSTRUCTIONS, digest,
                    threads_schema(), num_predict=1000)
    return _parse(raw, Threads, "patterns")


def group_topics(system_prompt: str, digest: str) -> Topics:
    """Sort a pile of notes into topic groups by what they're about."""
    raw = _complete(system_prompt + "\n\n" + TOPICS_JSON_INSTRUCTIONS, digest,
                    topics_schema(), num_predict=1200)
    return _parse(raw, Topics, "topics")


def _complete(system: str, user: str, schema: dict, num_predict: int) -> str:
    if PROVIDER == "ollama":
        return _call_ollama(system, user, schema, num_predict)
    if PROVIDER == "groq":
        return _call_groq(system, user)
    raise LLMError(f"Unknown LLM_PROVIDER={PROVIDER!r}. Use 'ollama' or 'groq'.")


def _parse(raw: str, model, what: str):
    # Be forgiving: strip stray code fences some models add despite instructions.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        return model.model_validate_json(raw)
    except Exception as exc:  # ValidationError or JSON error
        raise LLMError(f"Model returned malformed {what}: {exc}") from exc


def _call_ollama(system: str, note: str, schema: dict, num_predict: int) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": note},
        ],
        "stream": False,
        "format": schema,              # Ollama enforces this JSON schema
        "options": {"temperature": 0.4, "num_predict": num_predict},
    }
    try:
        # Long timeout: small models on CPU can run a minute or more per note.
        resp = httpx.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=600)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(
            f"Could not reach Ollama at {OLLAMA_HOST}. Is it running and is the "
            f"model '{OLLAMA_MODEL}' pulled?  ({exc})"
        ) from exc
    return resp.json()["message"]["content"]


def _call_groq(system: str, note: str) -> str:
    if not GROQ_KEY:
        raise LLMError("GROQ_API_KEY is not set. Get a free key at console.groq.com.")
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": note},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},   # forces valid JSON
    }
    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"Groq API error: {exc}") from exc
    return resp.json()["choices"][0]["message"]["content"]
