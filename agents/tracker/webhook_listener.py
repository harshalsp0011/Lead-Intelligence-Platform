from __future__ import annotations

"""SendGrid webhook listener for tracking outreach events.

Purpose:
- Receives SendGrid webhook events (open/click/bounce/unsubscribe/reply),
  normalizes them, and forwards them to tracker processing.

Dependencies:
- `fastapi` and `uvicorn` for HTTP listener runtime.
- `config.settings.get_settings` for SendGrid key used in simple HMAC validation.
- `agents.tracker.tracker_agent.process_event` for downstream event handling.

Usage:
- Call `start_listener(port=8002)` from a tracker service entrypoint.
"""

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from config.settings import get_settings

logger = logging.getLogger(__name__)

_SENDGRID_EVENT_MAP = {
    "open": "opened",
    "click": "clicked",
    "bounce": "bounced",
    "unsubscribe": "unsubscribed",
    "inbound": "replied",
}


def start_listener(port: int = 8002) -> None:
    """Start webhook server and run continuously on the provided port."""
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI(title="SendGrid Webhook Listener")

    @app.post("/webhooks/email")
    async def _email_webhook(request: Request) -> JSONResponse:
        return await receive_webhook(request)

    uvicorn.run(app, host="0.0.0.0", port=int(port), log_level="info")


async def receive_webhook(request: Request) -> JSONResponse:
    """Receive webhook request, process events, and always return HTTP 200."""
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="ignore")

    try:
        valid = validate_webhook(dict(request.headers), body_text)
        if not valid:
            logger.warning("Webhook signature validation failed or missing; continuing in phase 1")

        events = parse_sendgrid_event(body_text)
        tracker_agent = _import_tracker_agent()

        for event in events:
            if tracker_agent is None:
                logger.warning("tracker_agent not available; dropping event %s", event)
                continue
            tracker_agent.process_event(event)
    except Exception:
        logger.exception("Webhook processing error; returning HTTP 200 to prevent SendGrid retry storms")

    return JSONResponse(status_code=200, content={"ok": True})


def parse_sendgrid_event(raw_payload: str) -> list[dict[str, Any]]:
    """Parse SendGrid webhook JSON payload and return normalized event dictionaries."""
    try:
        payload = json.loads(raw_payload or "[]")
    except json.JSONDecodeError:
        logger.warning("Invalid SendGrid webhook JSON payload")
        return []

    if not isinstance(payload, list):
        logger.warning("SendGrid webhook payload is not an array")
        return []

    parsed_events: list[dict[str, Any]] = []

    for raw_event in payload:
        if not isinstance(raw_event, dict):
            continue

        raw_event_type = str(raw_event.get("event") or "").strip().lower()
        standard_type = _SENDGRID_EVENT_MAP.get(raw_event_type, raw_event_type)

        timestamp_value = raw_event.get("timestamp")
        timestamp = _to_datetime(timestamp_value)

        message_id = str(
            raw_event.get("sg_message_id")
            or raw_event.get("smtp-id")
            or raw_event.get("message_id")
            or ""
        )

        event_dict: dict[str, Any] = {
            "event_type": standard_type,
            "message_id": message_id,
            "email": str(raw_event.get("email") or ""),
            "timestamp": timestamp,
            "reply_content": None,
        }

        if standard_type == "replied":
            event_dict["reply_content"] = extract_reply_content(raw_event)

        parsed_events.append(event_dict)

    return parsed_events


def validate_webhook(headers: dict[str, Any], body: str) -> bool:
    """Validate SendGrid webhook with simple HMAC body signature check."""
    signature = _read_signature_header(headers)
    if not signature:
        logger.warning("No SendGrid signature header present")
        return False

    settings = get_settings()
    secret = str(settings.SENDGRID_API_KEY or "")
    if not secret:
        logger.warning("SENDGRID_API_KEY missing; cannot validate webhook signature")
        return False

    computed = hmac.new(
        key=secret.encode("utf-8"),
        msg=(body or "").encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    provided = signature.strip().lower().removeprefix("sha256=")
    return hmac.compare_digest(computed, provided)


def extract_reply_content(sendgrid_inbound_event: dict[str, Any]) -> str:
    """Extract and clean human reply content from an inbound webhook event."""
    raw = str(
        sendgrid_inbound_event.get("text")
        or sendgrid_inbound_event.get("body")
        or sendgrid_inbound_event.get("content")
        or ""
    )

    lines = raw.splitlines()

    cleaned_lines: list[str] = []
    for line in lines:
        stripped = line.strip()

        # Drop quoted reply chains.
        if stripped.startswith(">"):
            continue

        # Stop on common reply separators/signatures.
        if stripped.lower().startswith("on ") and " wrote:" in stripped.lower():
            break
        if stripped in {"--", "---"}:
            break
        if re.match(r"^(thanks|thank you|best|regards|sincerely)[,!\s]*$", stripped, flags=re.IGNORECASE):
            cleaned_lines.append(stripped)
            break

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned.strip()


def _read_signature_header(headers: dict[str, Any]) -> str:
    for key, value in headers.items():
        lower_key = str(key).lower()
        if lower_key in {
            "x-twilio-email-event-webhook-signature",
            "x-sendgrid-signature",
            "x-sendgrid-event-webhook-signature",
        }:
            return str(value or "")
    return ""


def _to_datetime(timestamp_value: Any) -> datetime:
    if isinstance(timestamp_value, (int, float)):
        return datetime.fromtimestamp(float(timestamp_value), tz=timezone.utc)

    if isinstance(timestamp_value, str):
        stripped = timestamp_value.strip()
        if stripped.isdigit():
            return datetime.fromtimestamp(float(stripped), tz=timezone.utc)
        try:
            return datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            pass

    return datetime.now(tz=timezone.utc)


def _import_tracker_agent() -> Any:
    try:
        module = import_module("agents.tracker.tracker_agent")
        return module
    except Exception:
        logger.warning("Could not import agents.tracker.tracker_agent")
        return None
