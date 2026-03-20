from __future__ import annotations

"""Email notification sender for human-in-loop approval steps.

Sends emails via SendGrid for:
- Lead approval requests (after Analyst scores companies)
- Reply received alerts (auto, no human trigger)
- Pipeline run completion summaries

Usage:
    from agents.notifications.email_notifier import send_lead_approval_request
    send_lead_approval_request(leads, run_id, recipient_email)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _send_via_sendgrid(to_email: str, subject: str, html_body: str) -> bool:
    """Send an email via SendGrid. Returns True on success."""
    settings = get_settings()
    if not settings.SENDGRID_API_KEY:
        logger.warning("SendGrid API key not set — skipping email notification")
        return False

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        message = Mail(
            from_email=settings.SENDGRID_FROM_EMAIL,
            to_emails=to_email,
            subject=subject,
            html_content=html_body,
        )
        response = sg.send(message)
        if response.status_code in (200, 202):
            logger.info("Notification email sent to %s — subject: %s", to_email, subject)
            return True
        logger.warning("SendGrid returned status %s", response.status_code)
        return False
    except Exception as exc:
        logger.exception("Failed to send notification email: %s", exc)
        return False


def send_lead_approval_request(
    leads: list[dict[str, Any]],
    run_id: str,
    recipient_email: str,
    dashboard_url: str = "http://localhost:3000/leads",
) -> bool:
    """Send an approval request email listing scored leads.

    Called after Analyst completes scoring. The reviewer clicks a link to
    open the Leads page, review, and approve/reject.

    Args:
        leads: List of lead dicts with name, score, tier, savings_mid fields
        run_id: UUID of the agent run (for reference in email)
        recipient_email: Email address of the reviewer
        dashboard_url: URL of the leads review page

    Returns:
        True if email was sent successfully
    """
    high = [l for l in leads if l.get("tier") == "high"]
    medium = [l for l in leads if l.get("tier") == "medium"]

    rows_html = ""
    for lead in sorted(leads, key=lambda x: x.get("score", 0), reverse=True)[:20]:
        tier = lead.get("tier", "low")
        tier_color = {"high": "#16a34a", "medium": "#ca8a04", "low": "#6b7280"}.get(tier, "#6b7280")
        savings = lead.get("savings_mid", 0)
        savings_str = f"${savings / 1_000_000:.1f}M" if savings >= 1_000_000 else f"${savings / 1_000:.0f}k"
        rows_html += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{lead.get('name', '—')}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{lead.get('industry', '—')}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{lead.get('city', '—')}, {lead.get('state', '—')}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:center">
            <strong>{lead.get('score', 0):.0f}</strong>
          </td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:center">
            <span style="color:{tier_color};font-weight:bold">{tier.upper()}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{savings_str}</td>
        </tr>"""

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto">
      <h2 style="color:#1e40af">Troy &amp; Banks — Lead Review Required</h2>
      <p>Scout has finished scoring companies and found leads ready for your review.</p>

      <div style="background:#f0f9ff;border-left:4px solid #3b82f6;padding:16px;margin:20px 0">
        <strong>Run ID:</strong> {run_id}<br>
        <strong>High-tier leads:</strong> {len(high)}<br>
        <strong>Medium-tier leads:</strong> {len(medium)}<br>
        <strong>Total scored:</strong> {len(leads)}
      </div>

      <h3>Top Scored Companies</h3>
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead>
          <tr style="background:#f3f4f6">
            <th style="padding:8px;text-align:left">Company</th>
            <th style="padding:8px;text-align:left">Industry</th>
            <th style="padding:8px;text-align:left">Location</th>
            <th style="padding:8px;text-align:center">Score</th>
            <th style="padding:8px;text-align:center">Tier</th>
            <th style="padding:8px;text-align:left">Est. Savings</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>

      <div style="margin:30px 0;text-align:center">
        <a href="{dashboard_url}" style="background:#2563eb;color:white;padding:12px 28px;
           border-radius:6px;text-decoration:none;font-weight:bold;font-size:16px">
          Review &amp; Approve Leads →
        </a>
      </div>

      <p style="color:#6b7280;font-size:12px">
        Approve high-tier leads to continue the pipeline. Writer will generate emails
        only for approved companies.
      </p>
    </div>
    """

    subject = f"[Troy & Banks] {len(high)} High-Tier Leads Ready for Review"
    return _send_via_sendgrid(recipient_email, subject, html_body)


def send_reply_alert(
    company_name: str,
    contact_name: str,
    reply_snippet: str,
    sentiment: str,
    recipient_email: str,
) -> bool:
    """Send an alert email when a prospect replies.

    Args:
        company_name: Name of the company that replied
        contact_name: Name of the contact who replied
        reply_snippet: First 200 chars of the reply
        sentiment: 'positive', 'negative', or 'neutral'
        recipient_email: Sales team email

    Returns:
        True if email was sent successfully
    """
    sentiment_color = {"positive": "#16a34a", "negative": "#dc2626", "neutral": "#ca8a04"}.get(
        sentiment, "#6b7280"
    )

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1e40af">Troy &amp; Banks — Reply Received</h2>

      <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:16px;margin:20px 0">
        <strong>{company_name}</strong> has replied!<br>
        <strong>Contact:</strong> {contact_name}<br>
        <strong>Sentiment:</strong>
        <span style="color:{sentiment_color};font-weight:bold">{sentiment.upper()}</span>
      </div>

      <h3>Reply Preview</h3>
      <blockquote style="background:#f9fafb;border-left:4px solid #d1d5db;
         padding:12px;margin:0;color:#374151;font-style:italic">
        {reply_snippet}...
      </blockquote>

      <p style="margin-top:20px">Log in to the dashboard to see the full reply and update the deal status.</p>
    </div>
    """

    subject = f"[Troy & Banks] Reply from {company_name} — {sentiment.capitalize()}"
    return _send_via_sendgrid(recipient_email, subject, html_body)


def send_pipeline_summary(
    summary: dict[str, Any],
    recipient_email: str,
) -> bool:
    """Send a pipeline run completion summary email.

    Args:
        summary: Dict with companies_found, scored_high, scored_medium, drafts_created
        recipient_email: Recipient email

    Returns:
        True if email was sent successfully
    """
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1e40af">Troy &amp; Banks — Pipeline Run Complete</h2>

      <table style="width:100%;border-collapse:collapse;margin:20px 0">
        <tr>
          <td style="padding:12px;background:#f3f4f6;border-radius:6px;text-align:center">
            <div style="font-size:24px;font-weight:bold;color:#1e40af">
              {summary.get('companies_found', 0)}
            </div>
            <div style="font-size:12px;color:#6b7280">Companies Found</div>
          </td>
          <td style="width:16px"></td>
          <td style="padding:12px;background:#f0fdf4;border-radius:6px;text-align:center">
            <div style="font-size:24px;font-weight:bold;color:#16a34a">
              {summary.get('scored_high', 0)}
            </div>
            <div style="font-size:12px;color:#6b7280">High-Tier Leads</div>
          </td>
          <td style="width:16px"></td>
          <td style="padding:12px;background:#fefce8;border-radius:6px;text-align:center">
            <div style="font-size:24px;font-weight:bold;color:#ca8a04">
              {summary.get('drafts_created', 0)}
            </div>
            <div style="font-size:12px;color:#6b7280">Email Drafts Ready</div>
          </td>
        </tr>
      </table>

      <p>Log in to the dashboard to review and approve email drafts before they are sent.</p>
    </div>
    """

    subject = "[Troy & Banks] Pipeline Run Complete"
    return _send_via_sendgrid(recipient_email, subject, html_body)
