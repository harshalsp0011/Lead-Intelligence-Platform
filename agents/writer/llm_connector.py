from __future__ import annotations

"""LLM connector helpers for Writer workflows."""

import logging
from importlib import import_module
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = {"ollama", "openai"}


def call_ollama(prompt: str) -> str:
    """Send a prompt to Ollama chat API and return response text."""
    settings = get_settings()

    try:
        ollama = import_module("ollama")
    except ImportError as exc:
        raise RuntimeError("Ollama client library is not installed") from exc

    try:
        client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        response = client.chat(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise RuntimeError(
            f"Ollama not reachable at {settings.OLLAMA_BASE_URL}. "
            "Start with: ollama serve"
        ) from exc

    # ollama >= 0.4 returns ChatResponse object; older versions returned dict
    if isinstance(response, dict):
        message = response.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
    else:
        content = response.message.content if hasattr(response, "message") else None
    return str(content or "")


def call_openai(prompt: str) -> str:
    """Send a prompt to OpenAI chat completions API and return response text."""
    settings = get_settings()

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI client library is not installed") from exc

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        return str(content or "")
    except Exception as exc:
        logger.exception("OpenAI API error while generating writer content")
        raise RuntimeError("OpenAI API error while generating content") from exc


def select_provider() -> str:
    """Return validated LLM provider ('ollama' or 'openai')."""
    provider = (get_settings().LLM_PROVIDER or "").strip().lower()
    if provider not in _VALID_PROVIDERS:
        raise ValueError("LLM_PROVIDER must be 'ollama' or 'openai'")
    return provider
