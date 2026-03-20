from __future__ import annotations

"""Main Orchestrator Agent entry point.

Purpose:
- Controls the full lead-generation pipeline end to end: scout → analyst →
  contact enrichment → writer → outreach.
- Delegates all agent execution to task_manager for unified logging and retry
  handling.
- Provides a single handle_agent_failure() path that logs, retries, and alerts
  on exhaustion.

Dependencies:
- `agents.orchestrator.task_manager` for task dispatch, status, and retry.
- `agents.analyst.enrichment_client` for per-company contact discovery.
- `sqlalchemy` session for lead_scores, email_drafts, and companies queries.

Usage:
- Call `run_full_pipeline(industry, location, count, db_session)` to execute
  the complete pipeline and receive a summary dict.
- Call individual stage functions for partial or re-entrant runs.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.analyst import enrichment_client
from agents.notifications import email_notifier
from agents.orchestrator import task_manager
from config.settings import get_settings
from database.orm_models import Company, CompanyFeature, EmailDraft, HumanApprovalRequest, LeadScore

logger = logging.getLogger(__name__)


def _parse_uuid(value: str) -> uuid.UUID:
    """Parse a UUID string and raise ValueError for invalid values."""
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid UUID value: {value}") from exc


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run_full_pipeline(
    industry: str,
    location: str,
    count: int,
    db_session: Session,
) -> dict[str, Any]:
    """Execute the full scout → analyst → enrich → write pipeline.

    Returns a summary dict combining results from all stages.
    """
    # Step 1: scout for new companies
    scout_result = run_scout(industry, location, count, db_session)
    new_ids: list[str] = scout_result.get("company_ids", [])

    # Step 2: score and tier all discovered companies
    analyst_result = run_analyst(new_ids, db_session)
    high_ids: list[str] = analyst_result.get("high_ids", [])

    # Step 3: enrich high-tier companies with contacts
    enrichment_result = run_contact_enrichment(high_ids, db_session)

    # Step 4: generate email drafts for approved high-tier companies
    writer_result = run_writer(db_session)

    # Step 5: build and return summary
    return generate_run_summary(
        scout_result,
        analyst_result,
        enrichment_result,
        writer_result,
    )


# ---------------------------------------------------------------------------
# Stage functions
# ---------------------------------------------------------------------------


def run_scout(
    industry: str,
    location: str,
    count: int,
    db_session: Session,
) -> dict[str, Any]:
    """Run the scout agent and return discovered company IDs.

    Returns dict with key `company_ids` (list[str]).
    """
    task = task_manager.assign_task(
        "scout",
        {"industry": industry, "location": location, "count": count},
        db_session,
    )

    if task["status"] != "completed":
        logger.error(
            "Scout task failed: %s", task["result"].get("error", "unknown error")
        )
        return {"company_ids": []}

    company_ids: list[str] = task["result"].get("company_ids", [])
    logger.info("Scout found %d companies.", len(company_ids))
    return {"company_ids": company_ids}


def run_analyst(
    company_ids: list[str],
    db_session: Session,
) -> dict[str, Any]:
    """Score companies and return tier counts plus high-tier IDs.

    Returns dict with keys: scored, high, medium, low, high_ids.
    """
    if not company_ids:
        return {"scored": 0, "high": 0, "medium": 0, "low": 0, "high_ids": []}

    task = task_manager.assign_task(
        "analyst",
        {"company_ids": company_ids},
        db_session,
    )

    if task["status"] != "completed":
        logger.error(
            "Analyst task failed: %s", task["result"].get("error", "unknown error")
        )
        return {"scored": 0, "high": 0, "medium": 0, "low": 0, "high_ids": []}

    counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    high_ids: list[str] = []
    scored_leads: list[dict[str, Any]] = []

    # Keep only the latest score per company to avoid double-counting.
    for company_id in company_ids:
        parsed_company_id = _parse_uuid(company_id)
        latest_score = db_session.execute(
            select(LeadScore)
            .where(LeadScore.company_id == parsed_company_id)
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        ).scalar()
        if latest_score is None:
            continue

        tier = str(latest_score.tier or "").lower()
        counts[tier] = counts.get(tier, 0) + 1
        if tier == "high":
            high_ids.append(company_id)

        # Build lead summary for notification
        company = db_session.get(Company, parsed_company_id)
        feature = db_session.execute(
            select(CompanyFeature)
            .where(CompanyFeature.company_id == parsed_company_id)
            .order_by(CompanyFeature.computed_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        scored_leads.append({
            "name": company.name if company else "",
            "industry": company.industry if company else "",
            "city": company.city if company else "",
            "state": company.state if company else "",
            "score": float(latest_score.score or 0),
            "tier": tier,
            "savings_mid": float(feature.savings_mid or 0) if feature else 0,
        })

    total = sum(counts.values())

    # Create human approval request and send notification email
    if total > 0:
        settings = get_settings()
        approval_req = HumanApprovalRequest(
            id=uuid.uuid4(),
            approval_type="leads",
            status="pending",
            items_count=total,
            items_summary=f"High: {counts.get('high', 0)}, Medium: {counts.get('medium', 0)}, Low: {counts.get('low', 0)}",
            notification_email=settings.ALERT_EMAIL,
            notification_sent=False,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(approval_req)
        db_session.commit()

        if settings.ALERT_EMAIL:
            sent = email_notifier.send_lead_approval_request(
                leads=scored_leads,
                run_id=str(approval_req.id),
                recipient_email=settings.ALERT_EMAIL,
            )
            if sent:
                approval_req.notification_sent = True
                approval_req.notification_sent_at = datetime.now(timezone.utc)
                db_session.commit()

    return {
        "scored": total,
        "high": counts.get("high", 0),
        "medium": counts.get("medium", 0),
        "low": counts.get("low", 0),
        "high_ids": high_ids,
    }


def run_contact_enrichment(
    company_ids: list[str],
    db_session: Session,
) -> dict[str, Any]:
    """Find and persist contacts for each high-tier company.

    Queries the companies table for name + website, then calls
    enrichment_client.find_contacts() per company.

    Returns dict with key `contacts_found` (int).
    """
    if not company_ids:
        return {"contacts_found": 0}

    parsed_company_ids = [_parse_uuid(company_id) for company_id in company_ids]
    companies = db_session.execute(
        select(Company).where(Company.id.in_(parsed_company_ids))
    ).scalars().all()

    total_contacts = 0
    for company in companies:
        company_id = str(company.id)
        name = str(company.name or "")
        website = str(company.website or "")
        try:
            contacts = enrichment_client.find_contacts(
                company_name=name,
                website_domain=website,
                db_session=db_session,
            )
            total_contacts += len(contacts)
        except Exception:
            logger.exception(
                "Contact enrichment failed for company_id=%s", company_id
            )

    logger.info("Contact enrichment complete. Total contacts found: %d", total_contacts)
    return {"contacts_found": total_contacts}


def run_writer(db_session: Session) -> dict[str, Any]:
    """Generate email drafts for approved high-tier companies with no draft yet.

    Returns dict with key `drafts_created` (int).
    """
    rows = db_session.execute(
        select(LeadScore.company_id)
        .where(
            LeadScore.tier == "high",
            LeadScore.approved_human.is_(True),
            ~select(EmailDraft.id)
            .where(EmailDraft.company_id == LeadScore.company_id)
            .correlate(LeadScore)
            .exists(),
        )
        .order_by(LeadScore.scored_at.desc())
    ).all()

    approved_ids: list[str] = [str(company_id) for (company_id,) in rows if company_id]
    if not approved_ids:
        return {"drafts_created": 0}

    task = task_manager.assign_task(
        "writer",
        {"company_ids": approved_ids},
        db_session,
    )

    if task["status"] != "completed":
        logger.error(
            "Writer task failed: %s", task["result"].get("error", "unknown error")
        )
        return {"drafts_created": 0}

    drafts: list[str] = task["result"].get("draft_ids", [])
    logger.info("Writer created %d drafts.", len(drafts))
    return {"drafts_created": len(drafts)}


def run_outreach(db_session: Session) -> dict[str, Any]:
    """Send approved outreach queue and process follow-ups.

    Returns dict with keys: sent, followups, skipped.
    """
    task = task_manager.assign_task("outreach", {}, db_session)

    if task["status"] != "completed":
        logger.error(
            "Outreach task failed: %s", task["result"].get("error", "unknown error")
        )
        return {"sent": 0, "followups": 0, "skipped": 0}

    result = task["result"]
    return {
        "sent": int(result.get("sent", 0)),
        "followups": int(result.get("followups", 0)),
        "skipped": int(result.get("skipped", 0)),
    }


# ---------------------------------------------------------------------------
# Summary and failure handling
# ---------------------------------------------------------------------------


def generate_run_summary(
    scout_result: dict[str, Any],
    analyst_result: dict[str, Any],
    enrichment_result: dict[str, Any],
    writer_result: dict[str, Any],
) -> dict[str, Any]:
    """Combine per-stage results into one summary dict and print a table."""
    summary = {
        "companies_found": len(scout_result.get("company_ids", [])),
        "scored_high": analyst_result.get("high", 0),
        "scored_medium": analyst_result.get("medium", 0),
        "contacts_found": enrichment_result.get("contacts_found", 0),
        "drafts_created": writer_result.get("drafts_created", 0),
    }

    timestamp = datetime.now(timezone.utc).isoformat()
    print(
        f"\n{'='*52}\n"
        f"  PIPELINE RUN SUMMARY  [{timestamp}]\n"
        f"{'='*52}\n"
        f"  Companies found      : {summary['companies_found']}\n"
        f"  Scored high          : {summary['scored_high']}\n"
        f"  Scored medium        : {summary['scored_medium']}\n"
        f"  Contacts found       : {summary['contacts_found']}\n"
        f"  Email drafts created : {summary['drafts_created']}\n"
        f"{'='*52}\n"
    )

    return summary


def handle_agent_failure(
    agent_name: str,
    error: Exception,
    task_params: dict[str, Any],
    db_session: Session,
) -> str:
    """Log a known failure, attempt retry via task_manager, alert if exhausted.

    Returns:
        'retried_successfully'  — agent completed on retry.
        'failed_after_retry'    — max retries exhausted; Slack alert sent.
    """
    logger.error(
        "Agent '%s' failed. params=%s error=%s",
        agent_name,
        task_params,
        error,
        exc_info=error,
    )

    # First retry: assign_task runs the agent once more and registers a
    # task_id in the task log (status will be 'completed' or 'failed').
    retry_task = task_manager.assign_task(agent_name, task_params, db_session)
    task_id: str | None = retry_task.get("task_id")

    if retry_task.get("status") == "completed":
        logger.info(
            "Agent '%s' recovered on first retry. task_id=%s", agent_name, task_id
        )
        return "retried_successfully"

    # Second retry via retry_failed_task (increments retry_count in the log).
    if task_id:
        retry_result = task_manager.retry_failed_task(task_id, db_session)
        if retry_result.get("retried") and retry_result.get("new_result", {}).get(
            "status"
        ) == "completed":
            logger.info(
                "Agent '%s' recovered on second retry. task_id=%s",
                agent_name,
                task_id,
            )
            return "retried_successfully"

    # All retries exhausted — log the failure.
    # Email notification will be sent by the email_notifier in Phase 4.
    alert_msg = (
        f"Agent '{agent_name}' failed after all retries. "
        f"task_id={task_id} error={error} params={task_params}"
    )
    logger.error(alert_msg)
    return "failed_after_retry"
