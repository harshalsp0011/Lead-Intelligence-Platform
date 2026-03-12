from __future__ import annotations

"""Outreach email sender.

Purpose:
- Sends one draft email through the configured provider and logs send events.

Dependencies:
- `config.settings.get_settings` for provider keys and limits.
- `sqlalchemy` session for `email_drafts`, `contacts`, and `outreach_events` queries.
- `sendgrid` SDK for SendGrid delivery and `requests` for Instantly API calls.

Usage:
- Call `send_email(draft_id, db_session)` from outreach orchestration code.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from database.orm_models import Contact, EmailDraft, OutreachEvent

logger = logging.getLogger(__name__)

PROVIDER_SENDGRID = "sendgrid"
PROVIDER_INSTANTLY = "instantly"
EVENT_TYPE_SENT = "sent"
ENABLE_SENDGRID_OPEN_TRACKING = True
ENABLE_SENDGRID_CLICK_TRACKING = True
ENABLE_SENDGRID_TEXT_CLICK_TRACKING = True


def _parse_uuid(value: str) -> UUID | None:
    """Parse a string UUID value, returning None for invalid input."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def send_email(draft_id: str, db_session: Session) -> dict[str, Any]:
    """Send one approved draft through configured email provider."""
    draft_uuid = _parse_uuid(draft_id)
    if draft_uuid is None:
        logger.warning("Rejected send_email call with invalid draft_id=%s", draft_id)
        return {"success": False, "message_id": "Draft not found"}

    draft = db_session.execute(
        select(EmailDraft).where(EmailDraft.id == draft_uuid)
    ).scalar_one_or_none()

    if not draft:
        return {"success": False, "message_id": "Draft not found"}

    contact = db_session.execute(
        select(Contact).where(Contact.id == draft.contact_id)
    ).scalar_one_or_none()

    if not contact:
        return {"success": False, "message_id": "Contact not found"}

    if bool(contact.unsubscribed):
        return {"success": False, "message_id": "Skipped: contact unsubscribed"}

    daily_limit = check_daily_limit(db_session)
    if not bool(daily_limit.get("within_limit")):
        sent_today = int(daily_limit.get("sent_today") or 0)
        return {"success": False, "message_id": f"Skipped: daily limit reached ({sent_today})"}

    subject = str(draft.subject_line or "")
    body = add_unsubscribe_footer(str(draft.body or ""))
    to_email = str(contact.email or "")
    to_name = str(contact.full_name or "")

    if not to_email:
        return {"success": False, "message_id": "Contact email missing"}

    provider = select_provider()

    if provider == PROVIDER_SENDGRID:
        settings = get_settings()
        from_email = str(settings.SENDGRID_FROM_EMAIL or "")
        result = send_via_sendgrid(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body=body,
            from_email=from_email,
        )
    elif provider == PROVIDER_INSTANTLY:
        result = send_via_instantly(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body=body,
        )
    else:
        result = {"success": False, "message_id": f"Unsupported provider: {provider}"}

    if bool(result.get("success")):
        log_send_event(
            company_id=str(draft.company_id or ""),
            contact_id=str(contact.id or ""),
            draft_id=str(draft.id or ""),
            message_id=str(result.get("message_id") or ""),
            db_session=db_session,
        )
        db_session.commit()

    return {"success": bool(result.get("success")), "message_id": str(result.get("message_id") or "")}


def send_via_sendgrid(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    from_email: str,
) -> dict[str, Any]:
    """Send one email through SendGrid and return send result."""
    settings = get_settings()

    if not settings.SENDGRID_API_KEY:
        return {"success": False, "message_id": "SENDGRID_API_KEY is not set"}

    if not from_email:
        return {"success": False, "message_id": "SENDGRID_FROM_EMAIL is not set"}

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            ClickTracking,
            From,
            HtmlContent,
            Mail,
            OpenTracking,
            PlainTextContent,
            To,
            TrackingSettings,
        )

        client = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)

        mail = Mail(
            from_email=From(from_email),
            to_emails=To(to_email, to_name),
            subject=subject,
            plain_text_content=PlainTextContent(body),
            html_content=HtmlContent(body.replace("\n", "<br>")),
        )

        tracking = TrackingSettings()
        tracking.open_tracking = OpenTracking(enable=ENABLE_SENDGRID_OPEN_TRACKING)
        tracking.click_tracking = ClickTracking(
            enable=ENABLE_SENDGRID_CLICK_TRACKING,
            enable_text=ENABLE_SENDGRID_TEXT_CLICK_TRACKING,
        )
        mail.tracking_settings = tracking

        response = client.send(mail)

        if int(response.status_code) == 202:
            message_id = ""
            if isinstance(response.headers, dict):
                message_id = str(response.headers.get("X-Message-Id") or response.headers.get("x-message-id") or "")
            return {"success": True, "message_id": message_id}

        error_text = ""
        if isinstance(response.body, (bytes, bytearray)):
            error_text = response.body.decode("utf-8", errors="ignore")
        elif response.body is not None:
            error_text = str(response.body)
        return {"success": False, "message_id": f"SendGrid error {response.status_code}: {error_text}"}
    except Exception as exc:
        logger.exception("SendGrid send failed")
        return {"success": False, "message_id": f"SendGrid exception: {exc}"}


def send_via_instantly(to_email: str, to_name: str, subject: str, body: str) -> dict[str, Any]:
    """Send one email through Instantly API and return send result."""
    settings = get_settings()
    api_key = str(settings.INSTANTLY_API_KEY or "")
    campaign_id = str(settings.INSTANTLY_CAMPAIGN_ID or "")
    instantly_base_url = str(settings.INSTANTLY_API_BASE_URL or "").rstrip("/")

    if not api_key:
        return {"success": False, "message_id": "INSTANTLY_API_KEY is not set"}
    if not campaign_id:
        return {"success": False, "message_id": "INSTANTLY_CAMPAIGN_ID is not set"}

    try:
        response = requests.post(
            f"{instantly_base_url}/api/v1/lead/add",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "campaign_id": campaign_id,
                "email": to_email,
                "name": to_name,
                "subject": subject,
                "body": body,
            },
            timeout=settings.INSTANTLY_REQUEST_TIMEOUT_SECONDS,
        )

        payload = response.json() if response.content else {}
        if response.ok:
            message_id = str(payload.get("message_id") or payload.get("id") or "")
            return {"success": True, "message_id": message_id}

        return {"success": False, "message_id": str(payload.get("message") or response.text)}
    except Exception as exc:
        logger.exception("Instantly send failed")
        return {"success": False, "message_id": f"Instantly exception: {exc}"}


def select_provider() -> str:
    """Return configured email provider name."""
    provider = (get_settings().EMAIL_PROVIDER or PROVIDER_SENDGRID).strip().lower()
    if provider not in {PROVIDER_SENDGRID, PROVIDER_INSTANTLY}:
        logger.error("Unsupported EMAIL_PROVIDER configured: %s", provider)
        raise ValueError("EMAIL_PROVIDER must be 'sendgrid' or 'instantly'")
    return provider


def add_unsubscribe_footer(email_body: str) -> str:
    """Append standard unsubscribe footer to outgoing email body."""
    settings = get_settings()
    footer = (
        "\n\n---\n"
        f"{settings.UNSUBSCRIBE_INSTRUCTION}\n"
        f"{settings.TB_BRAND_NAME} | {settings.TB_OFFICE_LOCATION} | {settings.TB_PHONE}"
    )
    return f"{email_body}{footer}"


def check_daily_limit(db_session: Session) -> dict[str, Any]:
    """Return whether today's sent email count is below configured daily cap."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    sent_today = db_session.execute(
        select(func.count(OutreachEvent.id)).where(
            OutreachEvent.event_type == EVENT_TYPE_SENT,
            OutreachEvent.event_at >= start_of_day,
        )
    ).scalar_one()

    limit = int(get_settings().EMAIL_DAILY_LIMIT or 0)
    sent_count = int(sent_today or 0)

    return {
        "within_limit": sent_count < limit,
        "sent_today": sent_count,
    }


def log_send_event(
    company_id: str,
    contact_id: str,
    draft_id: str,
    message_id: str,
    db_session: Session,
) -> str:
    """Insert one outreach sent event row and return event UUID."""
    event = OutreachEvent(
        company_id=_parse_uuid(company_id),
        contact_id=_parse_uuid(contact_id),
        email_draft_id=_parse_uuid(draft_id),
        event_type=EVENT_TYPE_SENT,
        event_at=datetime.now(timezone.utc),
        reply_content=f"message_id:{message_id}",
        reply_sentiment=None,
        follow_up_number=0,
    )
    db_session.add(event)
    db_session.flush()
    return str(event.id)


class EmailSender:
    """Class-based interface for email sending operations (used by test suite)."""

    def add_unsubscribe_footer(self, email_body: str) -> str:
        """Append standard unsubscribe footer to outgoing email body."""
        return add_unsubscribe_footer(email_body)

    def select_provider(self) -> str:
        """Return configured email provider name."""
        return select_provider()

    def check_daily_limit(self, db_session: Session, daily_limit: int = None) -> dict[str, Any]:
        """Return whether today's sent email count is below configured daily cap."""
        result = check_daily_limit(db_session)
        
        # If custom limit provided, recalculate remaining
        if daily_limit is not None:
            sent_count = result['sent_today']
            result['within_limit'] = sent_count < daily_limit
            if sent_count >= daily_limit:
                result['remaining'] = 0
            else:
                result['remaining'] = daily_limit - sent_count
        else:
            # Use default limit
            limit = int(get_settings().EMAIL_DAILY_LIMIT or 0)
            sent_count = result['sent_today']
            if sent_count >= limit:
                result['remaining'] = 0
            else:
                result['remaining'] = limit - sent_count
        
        return result

    def send_email(
        self,
        contact: Any,
        subject: str,
        body: str,
        db_session: Session = None,
    ) -> dict[str, Any]:
        """Send email to contact (simplified for test interface)."""
        # Check if unsubscribed
        if hasattr(contact, 'unsubscribed') and contact.unsubscribed:
            return {'success': False, 'reason': 'contact_unsubscribed'}
        
        # Get email address
        to_email = getattr(contact, 'email', '')
        if not to_email:
            return {'success': False, 'reason': 'no_email'}
        
        # Select provider and send
        try:
            provider = select_provider()
            if provider == 'sendgrid':
                result = self._send_via_sendgrid(
                    to_email=to_email,
                    subject=subject,
                    body=body
                )
            elif provider == 'instantly':
                result = self._send_via_instantly(
                    to_email=to_email,
                    subject=subject,
                    body=body
                )
            else:
                result = {'success': False, 'message_id': f'Unknown provider: {provider}'}
            
            return result
        except Exception as exc:
            return {'success': False, 'reason': str(exc)}

    def _send_via_sendgrid(self, to_email: str, subject: str, body: str) -> dict[str, Any]:
        """Send via SendGrid (test wrapper)."""
        return send_via_sendgrid(
            to_email=to_email,
            to_name='',
            subject=subject,
            body=body,
            from_email=get_settings().SENDGRID_FROM_EMAIL or ''
        )

    def _send_via_instantly(self, to_email: str, subject: str, body: str) -> dict[str, Any]:
        """Send via Instantly (test wrapper)."""
        return send_via_instantly(
            to_email=to_email,
            to_name='',
            subject=subject,
            body=body
        )
