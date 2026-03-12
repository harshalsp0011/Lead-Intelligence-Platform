from __future__ import annotations

"""Daily and weekly reporting helpers for orchestrator workflows.

Purpose:
- Generates summary reports for sourcing, scoring, outreach, replies, and
  current high-tier pipeline value.

Dependencies:
- `sqlalchemy` session queries across companies, lead_scores, company_features,
  and outreach_events.
- `agents.orchestrator.pipeline_monitor` for active pipeline value rollups.

Usage:
- Call `generate_weekly_report(start_date, end_date, db_session)` for full
  report payloads used by dashboards, exports, or scheduled reporting jobs.
"""

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.orchestrator import pipeline_monitor
from database.orm_models import Company, CompanyFeature, LeadScore, OutreachEvent


def generate_weekly_report(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    db_session: Session,
) -> dict[str, Any]:
    """Generate a full report dictionary by combining all sub-metrics."""
    return {
        "date_range": {
            "start": _to_datetime_start(start_date).isoformat(),
            "end": _to_datetime_end(end_date).isoformat(),
        },
        "companies_found": count_companies_found(start_date, end_date, db_session),
        "leads_by_tier": count_leads_by_tier(start_date, end_date, db_session),
        "emails": count_emails_sent(start_date, end_date, db_session),
        "replies": count_replies_received(start_date, end_date, db_session),
        "pipeline_value": calculate_pipeline_value(db_session),
        "top_leads": get_top_leads(limit=10, db_session=db_session),
    }


def count_companies_found(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    db_session: Session,
) -> dict[str, Any]:
    """Return total discovered companies and grouped counts by industry/state."""
    start_dt, end_dt = _date_bounds(start_date, end_date)

    _date_filter = (Company.date_found >= start_dt, Company.date_found <= end_dt)
    total = db_session.execute(
        select(func.count(Company.id)).where(*_date_filter)
    ).scalar_one()

    industry_rows = db_session.execute(
        select(
            func.coalesce(Company.industry, "unknown").label("industry"),
            func.count(Company.id).label("count"),
        )
        .where(*_date_filter)
        .group_by(func.coalesce(Company.industry, "unknown"))
        .order_by(func.count(Company.id).desc())
    ).mappings().all()

    state_rows = db_session.execute(
        select(
            func.coalesce(Company.state, "unknown").label("state"),
            func.count(Company.id).label("count"),
        )
        .where(*_date_filter)
        .group_by(func.coalesce(Company.state, "unknown"))
        .order_by(func.count(Company.id).desc())
    ).mappings().all()

    return {
        "total": int(total or 0),
        "by_industry": {str(row["industry"]): int(row["count"] or 0) for row in industry_rows},
        "by_state": {str(row["state"]): int(row["count"] or 0) for row in state_rows},
    }


def count_leads_by_tier(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    db_session: Session,
) -> dict[str, int]:
    """Return scored lead counts by tier within the date range."""
    start_dt, end_dt = _date_bounds(start_date, end_date)

    rows = db_session.execute(
        select(
            func.coalesce(LeadScore.tier, "low").label("tier"),
            func.count(LeadScore.id).label("count"),
        )
        .where(LeadScore.scored_at >= start_dt, LeadScore.scored_at <= end_dt)
        .group_by(func.coalesce(LeadScore.tier, "low"))
    ).mappings().all()

    result = {"high": 0, "medium": 0, "low": 0}
    for row in rows:
        tier = str(row.get("tier") or "low").strip().lower()
        if tier not in result:
            continue
        result[tier] = int(row.get("count") or 0)

    result["total"] = result["high"] + result["medium"] + result["low"]
    return result


def count_emails_sent(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    db_session: Session,
) -> dict[str, Any]:
    """Return send/open/click totals and derived open/click rates."""
    start_dt, end_dt = _date_bounds(start_date, end_date)

    rows = db_session.execute(
        select(
            OutreachEvent.event_type.label("event_type"),
            func.count(OutreachEvent.id).label("count"),
        )
        .where(
            OutreachEvent.event_at >= start_dt,
            OutreachEvent.event_at <= end_dt,
            OutreachEvent.event_type.in_(["sent", "followup_sent", "opened", "clicked"]),
        )
        .group_by(OutreachEvent.event_type)
    ).mappings().all()

    counts = {str(row["event_type"]): int(row["count"] or 0) for row in rows}

    first_emails = counts.get("sent", 0)
    followups = counts.get("followup_sent", 0)
    opened = counts.get("opened", 0)
    clicked = counts.get("clicked", 0)
    total_sent = first_emails + followups

    open_rate_pct = (opened / total_sent * 100.0) if total_sent > 0 else 0.0
    click_rate_pct = (clicked / total_sent * 100.0) if total_sent > 0 else 0.0

    return {
        "total_sent": total_sent,
        "first_emails": first_emails,
        "followups": followups,
        "open_rate_pct": round(open_rate_pct, 2),
        "click_rate_pct": round(click_rate_pct, 2),
    }


def count_replies_received(
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    db_session: Session,
) -> dict[str, Any]:
    """Return reply sentiment totals, unsubscribe count, and reply rate."""
    start_dt, end_dt = _date_bounds(start_date, end_date)

    _reply_filter = (
        OutreachEvent.event_type == "replied",
        OutreachEvent.event_at >= start_dt,
        OutreachEvent.event_at <= end_dt,
    )
    sentiment_rows = db_session.execute(
        select(
            func.coalesce(OutreachEvent.reply_sentiment, "neutral").label("sentiment"),
            func.count(OutreachEvent.id).label("count"),
        )
        .where(*_reply_filter)
        .group_by(func.coalesce(OutreachEvent.reply_sentiment, "neutral"))
    ).mappings().all()

    replies_total = db_session.execute(
        select(func.count(OutreachEvent.id)).where(*_reply_filter)
    ).scalar_one()

    unsubscribes = db_session.execute(
        select(func.count(OutreachEvent.id)).where(
            OutreachEvent.event_type == "unsubscribed",
            OutreachEvent.event_at >= start_dt,
            OutreachEvent.event_at <= end_dt,
        )
    ).scalar_one()

    sent_total = db_session.execute(
        select(func.count(OutreachEvent.id)).where(
            OutreachEvent.event_type.in_(["sent", "followup_sent"]),
            OutreachEvent.event_at >= start_dt,
            OutreachEvent.event_at <= end_dt,
        )
    ).scalar_one()

    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for row in sentiment_rows:
        sentiment = str(row.get("sentiment") or "neutral").strip().lower()
        if sentiment in sentiment_counts:
            sentiment_counts[sentiment] = int(row.get("count") or 0)

    total_replies = int(replies_total or 0)
    sent_count = int(sent_total or 0)
    reply_rate_pct = (total_replies / sent_count * 100.0) if sent_count > 0 else 0.0

    return {
        "total_replies": total_replies,
        "positive": sentiment_counts["positive"],
        "neutral": sentiment_counts["neutral"],
        "negative": sentiment_counts["negative"],
        "unsubscribes": int(unsubscribes or 0),
        "reply_rate_pct": round(reply_rate_pct, 2),
    }


def calculate_pipeline_value(db_session: Session) -> dict[str, Any]:
    """Return active pipeline value using pipeline_monitor rollups."""
    values = pipeline_monitor.get_pipeline_value(db_session)
    return {
        "active_high_leads": int(values.get("total_leads_high") or 0),
        "total_savings_potential_low": float(values.get("total_savings_low") or 0.0),
        "total_savings_potential_mid": float(values.get("total_savings_mid") or 0.0),
        "total_savings_potential_high": float(values.get("total_savings_high") or 0.0),
        "troy_banks_revenue_estimate": float(values.get("total_tb_revenue_est") or 0.0),
    }


def get_top_leads(limit: int, db_session: Session) -> list[dict[str, Any]]:
    """Return top high-tier active leads ordered by score descending."""
    safe_limit = max(1, int(limit))

    _excluded: set[str] = {"lost", "archived", "no_response"}
    active_companies: list[Company] = list(db_session.execute(
        select(Company).where(Company.status.not_in(list(_excluded)))
    ).scalars().all())

    top_leads: list[dict[str, Any]] = []
    for company in active_companies:
        latest_score: LeadScore | None = db_session.execute(
            select(LeadScore)
            .where(LeadScore.company_id == company.id)
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        ).scalar()
        if not latest_score or latest_score.tier != "high":
            continue

        latest_feature: CompanyFeature | None = db_session.execute(
            select(CompanyFeature)
            .where(CompanyFeature.company_id == company.id)
            .order_by(CompanyFeature.computed_at.desc())
            .limit(1)
        ).scalar()

        savings_low = float(latest_feature.savings_low or 0.0) if latest_feature else 0.0
        savings_high = float(latest_feature.savings_high or 0.0) if latest_feature else 0.0
        top_leads.append(
            {
                "company_name": str(company.name or ""),
                "industry": str(company.industry or ""),
                "score": float(latest_score.score or 0.0),
                "tier": str(latest_score.tier or ""),
                "savings_formatted": f"{_fmt_currency(savings_low)} - {_fmt_currency(savings_high)}",
                "status": str(company.status or ""),
            }
        )

    top_leads.sort(key=lambda x: x["score"], reverse=True)
    return top_leads[:safe_limit]


def _date_bounds(start_date: date | datetime | str, end_date: date | datetime | str) -> tuple[datetime, datetime]:
    start_dt = _to_datetime_start(start_date)
    end_dt = _to_datetime_end(end_date)
    return start_dt, end_dt


def _to_datetime_start(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)

    parsed = datetime.fromisoformat(str(value))
    if parsed.time() == time.min:
        return datetime.combine(parsed.date(), time.min)
    return parsed


def _to_datetime_end(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.max)

    parsed = datetime.fromisoformat(str(value))
    if parsed.time() == time.min:
        return datetime.combine(parsed.date(), time.max)
    return parsed


def _fmt_currency(value: float) -> str:
    amount = float(value)
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    return f"${amount:.0f}"
