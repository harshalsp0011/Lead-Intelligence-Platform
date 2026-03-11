from __future__ import annotations

"""Sales alert sender for tracker workflows.

Purpose:
- Sends Slack and email alerts when high-intent lead replies are detected.

Dependencies:
- `requests` for Slack webhook posting.
- `config.settings.get_settings` for alert and sender configuration.
- `agents.outreach.email_sender.send_via_sendgrid` for email alerts.
- `agents.tracker.reply_classifier.should_alert_sales` for reply alert gating.

Usage:
- Call `should_alert(...)` after classifying an event.
- If True, send notifications with `send_slack_alert(...)` and/or `send_email_alert(...)`.
"""

from datetime import datetime
from typing import Any

import requests

from agents.outreach import email_sender
from agents.tracker import reply_classifier
from config.settings import get_settings


def send_slack_alert(
    company_name: str,
    contact_name: str,
    contact_title: str,
    savings_formatted: str,
    score: str,
    sentiment: str,
    reply_summary: str,
) -> bool:
    """Send hot-lead alert to Slack webhook and return success status."""
    settings = get_settings()
    webhook_url = str(settings.SLACK_WEBHOOK_URL or "").strip()
    if not webhook_url:
        return False

    # Function signature does not include company_id; keep a safe fallback in URL.
    message = build_alert_message(
        company_name=company_name,
        contact_name=contact_name,
        contact_title=contact_title,
        savings_formatted=savings_formatted,
        score=score,
        sentiment=sentiment,
        reply_summary=reply_summary,
        company_id="unknown",
    )

    try:
        response = requests.post(
            webhook_url,
            json={"text": message},
            timeout=15,
        )
        return response.status_code == 200
    except Exception:
        return False


def send_email_alert(
    to_email: str,
    company_name: str,
    contact_name: str,
    savings_formatted: str,
    score: str,
    sentiment: str,
    reply_summary: str,
    company_id: str,
) -> bool:
    """Send hot-lead alert email and return success status."""
    settings = get_settings()

    recipient = str(settings.ALERT_EMAIL or to_email or "").strip()
    if not recipient:
        return False

    subject = f"HOT LEAD: {company_name} replied — action needed"
    body = build_alert_message(
        company_name=company_name,
        contact_name=contact_name,
        contact_title="",
        savings_formatted=savings_formatted,
        score=score,
        sentiment=sentiment,
        reply_summary=reply_summary,
        company_id=company_id,
    )

    send_result = email_sender.send_via_sendgrid(
        to_email=recipient,
        to_name="Sales Team",
        subject=subject,
        body=body,
        from_email=str(settings.SENDGRID_FROM_EMAIL or ""),
    )
    return bool(send_result.get("success"))


def build_alert_message(
    company_name: str,
    contact_name: str,
    contact_title: str,
    savings_formatted: str,
    score: str,
    sentiment: str,
    reply_summary: str,
    company_id: str,
) -> str:
    """Build a multi-line alert message with dashboard deep-link."""
    header = f"HOT LEAD REPLY — {company_name}"
    contact_line = f"Contact: {contact_name}"
    if contact_title:
        contact_line = f"Contact: {contact_name} — {contact_title}"

    timestamp = format_alert_timestamp()
    dashboard_link = f"http://localhost:3000/leads/{company_id}"

    return (
        f"{header}\n"
        f"{contact_line}\n"
        f"Score: {score}/100\n"
        f"Est. Savings: {savings_formatted}\n"
        f"Sentiment: {sentiment}\n"
        f"Summary: {reply_summary}\n"
        f"Time: {timestamp}\n\n"
        f"Open Dashboard to respond → {dashboard_link}"
    )


def should_alert(event_type: str, sentiment: str, intent: str) -> bool:
    """Return True only for events/intents that require sales notification."""
    normalized_event = (event_type or "").strip().lower()

    if normalized_event == "replied":
        return reply_classifier.should_alert_sales(sentiment, intent)
    if normalized_event == "opened":
        return False
    if normalized_event == "clicked":
        return False
    if normalized_event == "bounced":
        return False
    return False


def format_alert_timestamp() -> str:
    """Return current timestamp in sales-alert display format."""
    now = datetime.now().astimezone()
    return now.strftime("%A %B %d %Y at %-I:%M %p %Z")
