from __future__ import annotations

"""Lead management API routes.

Purpose:
- CRUD-style endpoints for viewing, approving, and rejecting scored leads.
- GET /leads         — paginated lead list with optional filters
- GET /leads/high    — high-tier leads ordered by score
- GET /leads/{id}    — single lead details
- PATCH /leads/{id}/approve
- PATCH /leads/{id}/reject

Dependencies:
- `api.dependencies` for DB session and API key guard.
- `api.models.lead` for request/response schemas.
- SQLAlchemy text() queries against companies, company_features, lead_scores,
  contacts tables.

Usage:
- Include this router in api/main.py with prefix='/leads'.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dependencies import get_db, verify_api_key
from api.models.lead import (
    LeadApproveRequest,
    LeadFilterParams,
    LeadListResponse,
    LeadRejectRequest,
    LeadResponse,
)
from config.settings import get_settings
from database.orm_models import Company, CompanyFeature, Contact, LeadScore

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

TIER_LOW = "low"
TIER_MEDIUM = "medium"
TIER_HIGH = "high"
STATUS_NEW = "new"
STATUS_APPROVED = "approved"
STATUS_ARCHIVED = "archived"


def _latest_feature(db: Session, company_id: UUID) -> CompanyFeature | None:
    """Return the latest computed feature row for one company."""
    return db.execute(
        select(CompanyFeature)
        .where(CompanyFeature.company_id == company_id)
        .order_by(CompanyFeature.computed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_score(db: Session, company_id: UUID) -> LeadScore | None:
    """Return the latest score row for one company."""
    return db.execute(
        select(LeadScore)
        .where(LeadScore.company_id == company_id)
        .order_by(LeadScore.scored_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _contact_found(db: Session, company_id: UUID) -> bool:
    """Return True when the company has at least one non-unsubscribed contact."""
    return db.execute(
        select(Contact.id)
        .where(
            Contact.company_id == company_id,
            func.coalesce(Contact.unsubscribed, False).is_(False),
        )
        .limit(1)
    ).first() is not None


def _row_from_models(
    db: Session,
    company: Company,
    feature: CompanyFeature | None,
    score: LeadScore | None,
) -> dict[str, Any]:
    """Assemble a lead response payload from ORM model instances."""
    return {
        "company_id": company.id,
        "company_name": company.name,
        "industry": company.industry or "",
        "state": company.state or "",
        "site_count": company.site_count or 0,
        "employee_count": company.employee_count or 0,
        "estimated_total_spend": getattr(feature, "estimated_total_spend", 0.0) or 0.0,
        "savings_low": getattr(feature, "savings_low", 0.0) or 0.0,
        "savings_mid": getattr(feature, "savings_mid", 0.0) or 0.0,
        "savings_high": getattr(feature, "savings_high", 0.0) or 0.0,
        "score": getattr(score, "score", 0.0) or 0.0,
        "tier": getattr(score, "tier", TIER_LOW) or TIER_LOW,
        "score_reason": getattr(score, "score_reason", "") or "",
        "approved_human": bool(getattr(score, "approved_human", False) or False),
        "approved_by": getattr(score, "approved_by", None),
        "approved_at": getattr(score, "approved_at", None),
        "status": company.status or STATUS_NEW,
        "contact_found": _contact_found(db, company.id),
        "date_scored": getattr(score, "scored_at", None) or datetime.now(timezone.utc),
        "updated_at": company.updated_at or datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_currency(value: float) -> str:
    v = float(value or 0)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}k"
    return f"${v:.0f}"


def _build_lead_row(row: dict[str, Any], contingency_fee: float) -> LeadResponse:
    """Convert a normalized row dictionary into the public lead response schema."""
    savings_mid = float(row.get("savings_mid") or 0.0)
    return LeadResponse(
        company_id=row["company_id"],
        company_name=str(row.get("company_name") or ""),
        industry=str(row.get("industry") or ""),
        state=str(row.get("state") or ""),
        site_count=int(row.get("site_count") or 0),
        employee_count=int(row.get("employee_count") or 0),
        estimated_total_spend=float(row.get("estimated_total_spend") or 0.0),
        savings_low=float(row.get("savings_low") or 0.0),
        savings_mid=savings_mid,
        savings_high=float(row.get("savings_high") or 0.0),
        savings_low_formatted=_fmt_currency(float(row.get("savings_low") or 0.0)),
        savings_mid_formatted=_fmt_currency(savings_mid),
        savings_high_formatted=_fmt_currency(float(row.get("savings_high") or 0.0)),
        tb_revenue_estimate=round(savings_mid * contingency_fee, 2),
        score=float(row.get("score") or 0.0),
        tier=str(row.get("tier") or TIER_LOW),
        score_reason=str(row.get("score_reason") or ""),
        approved_human=bool(row.get("approved_human") or False),
        approved_by=row.get("approved_by"),
        approved_at=row.get("approved_at"),
        status=str(row.get("status") or STATUS_NEW),
        contact_found=bool(row.get("contact_found") or False),
        date_scored=row.get("date_scored") or datetime.now(timezone.utc),
    )


def _query_leads(
    db: Session,
    filters: LeadFilterParams,
    forced_tier: str | None = None,
    order_by: str = "c.updated_at DESC",
) -> tuple[int, int, int, int, list[dict[str, Any]]]:
    """Run the leads query and return (total, high, medium, low, rows)."""
    query = select(Company)

    if filters.industry:
        query = query.where(Company.industry == filters.industry)
    if filters.state:
        query = query.where(Company.state == filters.state)
    if filters.status:
        query = query.where(Company.status == filters.status)

    companies = db.execute(query).scalars().all()
    applied_tier = forced_tier or filters.tier
    rows: list[dict[str, Any]] = []

    for company in companies:
        feature = _latest_feature(db, company.id)
        score = _latest_score(db, company.id)
        row = _row_from_models(db, company, feature, score)

        if applied_tier and row["tier"] != applied_tier:
            continue
        if filters.min_score is not None and float(row["score"] or 0.0) < filters.min_score:
            continue
        if filters.max_score is not None and float(row["score"] or 0.0) > filters.max_score:
            continue
        if filters.date_from and row["date_scored"] < filters.date_from:
            continue
        if filters.date_to and row["date_scored"] > filters.date_to:
            continue

        rows.append(row)

    def _aware(dt: Any) -> datetime:
        """Return an offset-aware datetime — makes naive DB timestamps comparable."""
        if not dt:
            return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(dt, datetime) and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    if order_by == "score DESC":
        rows.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    else:
        rows.sort(key=lambda item: _aware(item.get("updated_at")), reverse=True)

    total = len(rows)
    high = sum(1 for row in rows if row.get("tier") == TIER_HIGH)
    medium = sum(1 for row in rows if row.get("tier") == TIER_MEDIUM)
    low = sum(1 for row in rows if row.get("tier") not in {TIER_HIGH, TIER_MEDIUM})

    page = max(1, filters.page)
    page_size = max(1, min(100, filters.page_size))
    offset = (page - 1) * page_size
    return total, high, medium, low, rows[offset: offset + page_size]


# ---------------------------------------------------------------------------
# Routes  (literal paths before parameterised ones)
# ---------------------------------------------------------------------------

@router.get("/high", response_model=LeadListResponse)
def list_high_leads(
    filters: LeadFilterParams = Depends(),
    db: Session = Depends(get_db),
) -> LeadListResponse:
    """Return high-tier leads ordered by score descending."""
    settings = get_settings()
    fee = float(getattr(settings, "TB_CONTINGENCY_FEE", 0.24) or 0.24)

    total, high, medium, low, rows = _query_leads(
        db, filters, forced_tier="high", order_by="score DESC"
    )
    leads = [_build_lead_row(r, fee) for r in rows]
    return LeadListResponse(
        leads=leads,
        total_count=total,
        high_count=high,
        medium_count=medium,
        low_count=low,
        page=filters.page,
        page_size=filters.page_size,
    )


@router.get("", response_model=LeadListResponse)
def list_leads(
    filters: LeadFilterParams = Depends(),
    db: Session = Depends(get_db),
) -> LeadListResponse:
    """Return paginated leads with optional filters."""
    settings = get_settings()
    fee = float(getattr(settings, "TB_CONTINGENCY_FEE", 0.24) or 0.24)

    total, high, medium, low, rows = _query_leads(
        db, filters, order_by="c.updated_at DESC"
    )
    leads = [_build_lead_row(r, fee) for r in rows]
    return LeadListResponse(
        leads=leads,
        total_count=total,
        high_count=high,
        medium_count=medium,
        low_count=low,
        page=filters.page,
        page_size=filters.page_size,
    )


@router.get("/{company_id}", response_model=LeadResponse)
def get_lead(company_id: UUID, db: Session = Depends(get_db)) -> LeadResponse:
    """Return full lead details for a single company."""
    settings = get_settings()
    fee = float(settings.TB_CONTINGENCY_FEE or 0.0)

    company = db.execute(
        select(Company).where(Company.id == company_id)
    ).scalar_one_or_none()

    if not company:
        logger.warning("Lead lookup failed; company_id=%s not found", company_id)
        raise HTTPException(status_code=404, detail=f"Lead {company_id} not found.")

    row = _row_from_models(db, company, _latest_feature(db, company_id), _latest_score(db, company_id))
    return _build_lead_row(row, fee)


@router.patch("/{company_id}/approve")
def approve_lead(
    company_id: UUID,
    body: LeadApproveRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve a lead: marks lead_scores and sets company status to 'approved'."""
    score_row = _latest_score(db, company_id)

    if not score_row:
        logger.warning("Lead approval failed; no lead score found for company_id=%s", company_id)
        raise HTTPException(
            status_code=404,
            detail=f"No lead score found for company {company_id}.",
        )

    score_row.approved_human = True
    score_row.approved_by = body.approved_by
    score_row.approved_at = datetime.now(timezone.utc)

    company = db.execute(
        select(Company).where(Company.id == company_id)
    ).scalar_one_or_none()
    if company is not None:
        company.status = STATUS_APPROVED
        company.updated_at = datetime.now(timezone.utc)

    db.commit()

    logger.info("Lead %s approved by %s", company_id, body.approved_by)
    return {"success": True, "message": f"Lead {company_id} approved by {body.approved_by}."}


@router.patch("/{company_id}/reject")
def reject_lead(
    company_id: UUID,
    body: LeadRejectRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Reject a lead: clears approval flag and archives the company."""
    score_rows = db.execute(
        select(LeadScore).where(LeadScore.company_id == company_id)
    ).scalars().all()
    for score_row in score_rows:
        score_row.approved_human = False

    company = db.execute(
        select(Company).where(Company.id == company_id)
    ).scalar_one_or_none()
    if company is not None:
        company.status = STATUS_ARCHIVED
        company.updated_at = datetime.now(timezone.utc)

    db.commit()

    logger.info(
        "Lead %s rejected by %s. reason=%s",
        company_id,
        body.rejected_by,
        body.rejection_reason,
    )
    return {
        "success": True,
        "message": (
            f"Lead {company_id} rejected by {body.rejected_by}. "
            f"Reason: {body.rejection_reason or 'not provided'}."
        ),
    }
