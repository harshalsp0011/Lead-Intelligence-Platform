from __future__ import annotations

"""Pipeline trigger API routes.

Purpose:
- Endpoints that kick off pipeline stages as FastAPI background tasks and
  expose a status-polling endpoint.
- POST /trigger/full      — full scout→analyst→enrich→write pipeline
- POST /trigger/scout     — scout only
- POST /trigger/analyst   — analyst only (queries unscored companies)
- POST /trigger/writer    — writer only (approved high-tier companies)
- POST /trigger/outreach  — outreach only
- GET  /trigger/{id}/status — poll trigger status

Dependencies:
- `api.dependencies` for DB session and API key guard.
- `api.models.trigger` for request/response schemas.
- `agents.orchestrator.orchestrator` for pipeline stage functions.
- `database.connection.SessionLocal` for background-task DB sessions.

Usage:
- Include this router in api/main.py with prefix='/trigger'.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_db, verify_api_key
from api.models.trigger import TriggerRequest, TriggerResponse, TriggerStatusResponse
from database.connection import SessionLocal
from database.orm_models import Company

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# In-process trigger registry  {trigger_id: status_dict}
_REGISTRY: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


def _wrap(trigger_id: str, fn: Any, *args: Any) -> None:
    """Run fn(*args) in background, updating the registry on completion."""
    db: Session = SessionLocal()
    try:
        result = fn(*args, db)
        _REGISTRY[trigger_id].update(
            status="completed",
            completed_at=datetime.now(timezone.utc),
            result_summary=result if isinstance(result, dict) else {"result": result},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Trigger %s failed: %s", trigger_id, exc)
        _REGISTRY[trigger_id].update(
            status="failed",
            completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
        )
    finally:
        db.close()


def _register(run_mode: str, req_dict: dict[str, Any]) -> tuple[str, datetime]:
    """Create a registry entry and return (trigger_id, started_at)."""
    trigger_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    _REGISTRY[trigger_id] = {
        "run_mode": run_mode,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "result_summary": None,
        "error_message": None,
        **req_dict,
    }
    return trigger_id, started_at


def _trigger_response(
    trigger_id: str,
    started_at: datetime,
    run_mode: str,
    industry: str = "",
    location: str = "",
    count: int = 0,
) -> TriggerResponse:
    return TriggerResponse(
        trigger_id=UUID(trigger_id),
        run_mode=run_mode,
        industry=industry,
        location=location,
        count=count,
        started_at=started_at,
        status="started",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/full", response_model=TriggerResponse)
def trigger_full(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
) -> TriggerResponse:
    """Start the full pipeline (scout → analyst → enrich → write) in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register(
        "full",
        {"industry": body.industry, "location": body.location, "count": body.count},
    )

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_full_pipeline(
            body.industry, body.location, body.count, db
        )

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(
        trigger_id, started_at, "full",
        body.industry, body.location, body.count,
    )


@router.post("/scout", response_model=TriggerResponse)
def trigger_scout(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
) -> TriggerResponse:
    """Run the scout stage in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register(
        "scout_only",
        {"industry": body.industry, "location": body.location, "count": body.count},
    )

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_scout(body.industry, body.location, body.count, db)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(
        trigger_id, started_at, "scout_only",
        body.industry, body.location, body.count,
    )


@router.post("/analyst", response_model=TriggerResponse)
def trigger_analyst(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Run the analyst stage for all unscored companies in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    # Gather company IDs that need scoring.
    company_ids: list[str] = [
        str(cid) for cid in db.execute(
            select(Company.id)
            .where(Company.status.in_(["new", "enriched"]))
            .order_by(Company.created_at.asc())
        ).scalars().all()
    ]

    trigger_id, started_at = _register(
        "analyst_only", {"company_ids_count": len(company_ids)}
    )
    _REGISTRY[trigger_id]["progress"] = []
    _REGISTRY[trigger_id]["total"] = len(company_ids)

    def _on_progress(entry: dict[str, Any]) -> None:
        _REGISTRY[trigger_id]["progress"].append(entry)

    def _run(session: Session) -> dict[str, Any]:
        return orchestrator.run_analyst(company_ids, session, on_progress=_on_progress)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "analyst_only")


@router.post("/enrich", response_model=TriggerResponse)
def trigger_enrich(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Run contact enrichment for human-approved companies only."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    # Only approved companies — human must have reviewed before we spend API credits
    company_ids: list[str] = [
        str(cid) for cid in db.execute(
            select(Company.id)
            .where(Company.status == "approved")
            .order_by(Company.created_at.asc())
        ).scalars().all()
    ]

    trigger_id, started_at = _register(
        "enrich_only", {"company_ids_count": len(company_ids)}
    )
    _REGISTRY[trigger_id]["progress"] = []
    _REGISTRY[trigger_id]["total"] = len(company_ids)

    def _on_progress(entry: dict[str, Any]) -> None:
        _REGISTRY[trigger_id]["progress"].append(entry)

    def _run(session: Session) -> dict[str, Any]:
        return orchestrator.run_contact_enrichment(company_ids, session, on_progress=_on_progress)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "enrich_only")


@router.post("/auto-approve", response_model=TriggerResponse)
def trigger_auto_approve(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Auto-approve all companies that already have at least one contact.

    These companies have already been enriched — a real email was found for them —
    so they are ready for outreach without needing manual review.
    Sets company.status = 'approved' and lead_scores.approved_human = True.
    """
    from database.orm_models import Contact, LeadScore  # noqa: PLC0415

    # Companies with at least one contact that are not yet approved
    company_ids: list[str] = [
        str(cid) for cid in db.execute(
            select(Company.id)
            .where(
                Company.status != "approved",
                Company.id.in_(select(Contact.company_id).distinct()),
            )
        ).scalars().all()
    ]

    trigger_id, started_at = _register(
        "auto_approve", {"company_ids_count": len(company_ids)}
    )

    def _run(session: Session) -> dict[str, Any]:
        from database.orm_models import Contact as _Contact, LeadScore as _LeadScore  # noqa: PLC0415
        now = datetime.now(timezone.utc)
        approved = 0
        for cid in company_ids:
            cid_uuid = __import__("uuid").UUID(cid)
            company = session.execute(
                select(Company).where(Company.id == cid_uuid)
            ).scalar_one_or_none()
            if not company:
                continue
            company.status = "approved"
            company.updated_at = now

            # Mark lead score approved if one exists; create minimal one if not
            score_row = session.execute(
                select(_LeadScore)
                .where(_LeadScore.company_id == cid_uuid)
                .order_by(_LeadScore.scored_at.desc())
            ).scalar_one_or_none()
            if score_row:
                score_row.approved_human = True
                score_row.approved_by = "system (has contact)"
                score_row.approved_at = now
                session.add(score_row)
            session.add(company)
            approved += 1

        session.commit()
        return {"approved": approved}

    background_tasks.add_task(_wrap, trigger_id, _run)
    return _trigger_response(trigger_id, started_at, "auto_approve")


@router.post("/backfill-phones", response_model=TriggerResponse)
def trigger_backfill_phones(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Scrape phone numbers from company websites for all companies missing a phone.

    Iterates all companies that have a website URL but no phone stored.
    Uses BeautifulSoup to find tel: links and regex phone patterns on the homepage.
    Safe to run multiple times — only fills NULL phone fields.
    """
    from agents.analyst import enrichment_client  # noqa: PLC0415

    company_ids: list[str] = [
        str(cid) for cid in db.execute(
            select(Company.id)
            .where(Company.phone.is_(None))
        ).scalars().all()
    ]

    trigger_id, started_at = _register(
        "backfill_phones", {"company_ids_count": len(company_ids)}
    )

    def _run(session: Session) -> dict[str, Any]:
        companies = session.execute(
            select(Company).where(Company.id.in_([
                __import__('uuid').UUID(cid) for cid in company_ids
            ]))
        ).scalars().all()

        filled = 0
        for company in companies:
            if company.phone:
                continue
            name  = str(company.name  or "")
            city  = str(company.city  or "")
            state = str(company.state or "")
            phone = None
            try:
                phone = enrichment_client.lookup_phone_google_places(name, city, state)
            except Exception:
                pass
            if not phone:
                try:
                    phone = enrichment_client.lookup_phone_yelp(name, city, state)
                except Exception:
                    pass
            if not phone and company.website:
                try:
                    phone = enrichment_client.scrape_phone_from_website(company.website)
                except Exception:
                    pass
            if phone:
                company.phone = phone
                session.add(company)
                filled += 1

        session.commit()
        return {"phones_filled": filled, "companies_checked": len(companies)}

    background_tasks.add_task(_wrap, trigger_id, _run)
    return _trigger_response(trigger_id, started_at, "backfill_phones")


@router.post("/verify-emails", response_model=TriggerResponse)
def trigger_verify_emails(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Verify unverified contacts using Hunter → ZeroBounce, highest priority first.

    Priority order (to conserve free-tier credits):
      1. Named contact + executive title (CFO, CEO, Owner, Director...)
      2. Named contact with any title
      3. Personal-looking email (short local part, no generic prefix)
      4. Generic inboxes (info@, contact@, hello@) — skipped entirely

    Updates Contact.verified=True for valid, False for invalid.
    """
    import re as _re
    from agents.analyst.enrichment_client import verify_email, _SKIP_EMAIL_PREFIXES  # noqa: PLC0415
    from database.orm_models import Contact  # noqa: PLC0415

    _EXEC_TITLES = {"cfo","chief financial officer","ceo","chief executive officer",
                    "president","owner","co-owner","founder","director","vp","vice president",
                    "director of finance","vp finance","facilities manager","energy manager"}

    def _priority(c: "Contact") -> int:  # lower = higher priority
        email_local = (c.email or "").split("@")[0].lower()
        if email_local in _SKIP_EMAIL_PREFIXES:
            return 99  # generic inbox — skip
        title = (c.title or "").strip().lower()
        name  = (c.full_name or "").strip()
        if name and any(t in title for t in _EXEC_TITLES):
            return 1
        if name and title:
            return 2
        if name:
            return 3
        # Personal-looking: short local part with no generic prefix
        if _re.match(r'^[a-z]{1,2}[a-z]+$', email_local) or '.' in email_local or len(email_local) <= 10:
            return 4
        return 5

    all_unverified = db.execute(
        select(Contact).where(Contact.verified.is_(False))
    ).scalars().all()

    # Sort by priority, skip generics entirely
    prioritized = sorted(
        [c for c in all_unverified if _priority(c) < 99],
        key=_priority,
    )
    skipped_generics = len(all_unverified) - len(prioritized)

    unverified_ids = [str(c.id) for c in prioritized]

    trigger_id, started_at = _register(
        "verify_emails", {"unverified_count": len(unverified_ids), "skipped_generics": skipped_generics}
    )
    _REGISTRY[trigger_id]["progress"] = []
    _REGISTRY[trigger_id]["total"] = len(unverified_ids)

    def _run(session: Session) -> dict[str, Any]:
        import uuid as _uuid
        contacts = session.execute(
            select(Contact).where(Contact.id.in_([
                _uuid.UUID(cid) for cid in unverified_ids
            ]))
        ).scalars().all()

        # Re-sort inside the run (DB fetch order may differ)
        contacts_sorted = sorted(contacts, key=_priority)

        verified_count = 0
        invalid_count = 0
        no_credits_count = 0
        for idx, contact in enumerate(contacts_sorted, start=1):
            if not contact.email:
                continue
            is_valid = verify_email(contact.email)  # True / False / None
            if is_valid is True:
                contact.verified = True
                session.add(contact)
                verified_count += 1
                outcome = "valid"
            elif is_valid is False:
                contact.verified = False
                session.add(contact)
                invalid_count += 1
                outcome = "invalid"
            else:
                # None = quota exhausted / can't determine — leave contact untouched
                no_credits_count += 1
                outcome = "no_credits"
            _REGISTRY[trigger_id]["progress"].append({
                "idx": idx,
                "email": contact.email,
                "name": contact.full_name or "",
                "title": contact.title or "",
                "verified": is_valid,
                "outcome": outcome,
            })

        session.commit()
        return {
            "verified": verified_count,
            "invalid": invalid_count,
            "no_credits": no_credits_count,
            "total_checked": len(contacts_sorted),
            "skipped_generics": skipped_generics,
        }

    background_tasks.add_task(_wrap, trigger_id, _run)
    return _trigger_response(trigger_id, started_at, "verify_emails")


@router.post("/writer", response_model=TriggerResponse)
def trigger_writer(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    """Run the writer stage (approved companies with no draft) in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    # Count upfront so the progress bar shows the correct total from the start
    from database.orm_models import EmailDraft as _EmailDraft  # noqa: PLC0415
    pending_count: int = db.execute(
        select(Company.id)
        .where(
            Company.status == "approved",
            ~select(_EmailDraft.id)
            .where(_EmailDraft.company_id == Company.id)
            .correlate(Company)
            .exists(),
        )
    ).scalars().all().__len__()

    trigger_id, started_at = _register("writer_only", {})
    _REGISTRY[trigger_id]["progress"] = []
    _REGISTRY[trigger_id]["total"] = pending_count

    def _on_progress(entry: dict[str, Any]) -> None:
        _REGISTRY[trigger_id]["progress"].append(entry)

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_writer(db, on_progress=_on_progress)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "writer_only")


@router.post("/outreach", response_model=TriggerResponse)
def trigger_outreach(background_tasks: BackgroundTasks) -> TriggerResponse:
    """Run the outreach stage (send approved drafts + follow-ups) in background."""
    from agents.orchestrator import orchestrator  # noqa: PLC0415

    trigger_id, started_at = _register("outreach", {})

    def _run(db: Session) -> dict[str, Any]:
        return orchestrator.run_outreach(db)

    background_tasks.add_task(_wrap, trigger_id, _run)

    return _trigger_response(trigger_id, started_at, "outreach")


@router.get("/{trigger_id}/status", response_model=TriggerStatusResponse)
def trigger_status(trigger_id: UUID) -> TriggerStatusResponse:
    """Poll the current status of a trigger by its ID."""
    entry = _REGISTRY.get(str(trigger_id))
    if not entry:
        return TriggerStatusResponse(
            trigger_id=trigger_id,
            status="not_found",
            started_at=datetime.now(timezone.utc),
        )

    completed_at: datetime | None = entry.get("completed_at")
    duration: int | None = None
    if completed_at and entry.get("started_at"):
        duration = int((completed_at - entry["started_at"]).total_seconds())

    return TriggerStatusResponse(
        trigger_id=trigger_id,
        status=str(entry.get("status") or "unknown"),
        run_mode=entry.get("run_mode"),
        started_at=entry["started_at"],
        completed_at=completed_at,
        duration_seconds=duration,
        result_summary=entry.get("result_summary"),
        error_message=entry.get("error_message"),
        progress=entry.get("progress") or [],
        total=entry.get("total"),
    )
