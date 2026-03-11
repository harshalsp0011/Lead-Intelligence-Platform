from __future__ import annotations

"""Reply classification helpers for tracker workflows.

Purpose:
- Classifies inbound reply text into sentiment/intent with LLM-first logic and
  rule-based fallback for reliability.

Dependencies:
- Optional `agents.tracker.llm_connector` module expected to expose
  `classify_reply_sentiment(text)` and `call_llm(prompt)`.
- Optional `agents.writer.llm_connector` fallback for basic LLM prompt calls.

Usage:
- Call `classify_reply(reply_text)` after reply text is cleaned.
- Use `should_alert_sales(...)` to decide alert routing.
"""

from importlib import import_module
from typing import Any


def classify_reply(reply_text: str) -> dict[str, Any]:
    """Classify a reply into sentiment, intent, summary, and confidence."""
    connector = _get_tracker_llm_connector()

    if connector is not None:
        classifier = getattr(connector, "classify_reply_sentiment", None)
        if callable(classifier):
            try:
                llm_result = classifier(reply_text)
                if isinstance(llm_result, dict) and _is_valid_classification(llm_result):
                    return _normalize_classification(llm_result)
            except Exception:
                pass

    return rule_based_classify(reply_text)


def rule_based_classify(reply_text: str) -> dict[str, Any]:
    """Fallback reply classifier using keyword matching rules."""
    text = (reply_text or "").strip()
    lowered = text.lower()

    unsubscribe_keywords = [
        "unsubscribe",
        "remove me",
        "stop",
        "do not contact",
        "opt out",
    ]
    if _contains_any(lowered, unsubscribe_keywords):
        return {
            "sentiment": "negative",
            "intent": "unsubscribe",
            "summary": "Recipient requested to be removed from outreach.",
            "confidence": 0.98,
        }

    positive_keywords = [
        "interested",
        "tell me more",
        "schedule",
        "call",
        "meeting",
        "sounds good",
        "yes",
        "would like to",
        "can we",
        "please send",
    ]
    if _contains_any(lowered, positive_keywords):
        return {
            "sentiment": "positive",
            "intent": "wants_meeting",
            "summary": "Recipient showed interest and is open to a meeting or next step.",
            "confidence": 0.88,
        }

    info_keywords = [
        "more information",
        "send me",
        "details",
        "brochure",
        "how does it work",
        "what is",
    ]
    if _contains_any(lowered, info_keywords):
        return {
            "sentiment": "positive",
            "intent": "wants_info",
            "summary": "Recipient requested more information before deciding next steps.",
            "confidence": 0.84,
        }

    negative_keywords = [
        "not interested",
        "no thank you",
        "already have",
        "happy with current",
        "no need",
        "wrong person",
    ]
    if _contains_any(lowered, negative_keywords):
        return {
            "sentiment": "negative",
            "intent": "not_interested",
            "summary": "Recipient declined and is not interested at this time.",
            "confidence": 0.9,
        }

    return {
        "sentiment": "neutral",
        "intent": "other",
        "summary": "Reply did not contain a clear positive or negative action signal.",
        "confidence": 0.6,
    }


def extract_reply_intent(reply_text: str) -> str:
    """Return only the intent field from a classified reply."""
    classification = classify_reply(reply_text)
    return str(classification.get("intent") or "other")


def generate_reply_summary(
    reply_text: str,
    company_name: str,
    contact_name: str,
    sentiment: str,
) -> str:
    """Generate a two-line sales alert summary from a reply."""
    prompt = (
        "Summarize this email reply in exactly 2 lines for a sales team.\n"
        f"From: {contact_name} at {company_name}\n"
        f"Sentiment: {sentiment}\n"
        f"Reply: {reply_text}\n"
        "Line 1: What they said\n"
        "Line 2: Recommended next action"
    )

    connector = _get_tracker_llm_connector()
    if connector is not None:
        caller = getattr(connector, "call_llm", None)
        if callable(caller):
            try:
                response = caller(prompt)
                summary = str(response or "").strip()
                if summary:
                    return summary
            except Exception:
                pass

    # Fallback to writer connector provider call if tracker connector is unavailable.
    writer_connector = _get_writer_llm_connector()
    if writer_connector is not None:
        try:
            provider = writer_connector.select_provider()
            if provider == "openai":
                return str(writer_connector.call_openai(prompt) or "").strip()
            return str(writer_connector.call_ollama(prompt) or "").strip()
        except Exception:
            pass

    line_1 = f"{contact_name} at {company_name} replied with {sentiment} sentiment."
    line_2 = "Review reply and decide whether to schedule a call, send info, or close loop."
    return f"{line_1}\n{line_2}"


def should_alert_sales(sentiment: str, intent: str) -> bool:
    """Return True when reply should trigger a sales alert."""
    normalized_sentiment = (sentiment or "").strip().lower()
    normalized_intent = (intent or "").strip().lower()

    if normalized_sentiment == "negative":
        return False
    if normalized_intent in {"not_interested", "unsubscribe"}:
        return False

    if normalized_sentiment == "positive":
        return True
    if normalized_intent in {"wants_meeting", "wants_info"}:
        return True

    return False


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_valid_classification(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    required_keys = {"sentiment", "intent", "summary", "confidence"}
    if not required_keys.issubset(set(value.keys())):
        return False

    sentiment = str(value.get("sentiment") or "").strip().lower()
    intent = str(value.get("intent") or "").strip().lower()
    summary = str(value.get("summary") or "").strip()

    try:
        confidence = float(value.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False

    if sentiment not in {"positive", "neutral", "negative"}:
        return False
    if intent not in {"wants_meeting", "wants_info", "not_interested", "unsubscribe", "other"}:
        return False
    if not summary:
        return False
    if confidence < 0 or confidence > 1:
        return False

    return True


def _normalize_classification(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "sentiment": str(value.get("sentiment") or "neutral").strip().lower(),
        "intent": str(value.get("intent") or "other").strip().lower(),
        "summary": str(value.get("summary") or "").strip(),
        "confidence": float(value.get("confidence") or 0.0),
    }


def _get_tracker_llm_connector() -> Any:
    try:
        return import_module("agents.tracker.llm_connector")
    except Exception:
        return None


def _get_writer_llm_connector() -> Any:
    try:
        return import_module("agents.writer.llm_connector")
    except Exception:
        return None
