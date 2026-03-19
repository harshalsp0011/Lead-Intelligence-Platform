from __future__ import annotations

"""Scout Critic — evaluates quality of a batch of discovered companies.

Purpose:
- After each source attempt, the Critic scores the batch 0.0–10.0.
- Scout uses this score to decide: move forward OR try another source.
- Also writes results to source_performance table so the agent learns
  which sources work best per industry/location over time.

Quality rubric (total = 10.0):
  - Website present       : 5.0 points  (most important — needed for enrichment)
  - City present          : 3.0 points  (needed for targeting)
  - Phone present         : 2.0 points  (nice to have — often missing, that is fine)

Thresholds:
  - score >= 6.0 : good quality batch
  - score < 6.0  : low quality — Scout should try another source if count not met

Dependencies:
- database.orm_models.SourcePerformance
- sqlalchemy

Usage:
    from agents.scout.scout_critic import evaluate_quality, update_source_performance
    score = evaluate_quality(companies)
    update_source_performance("google_maps", "healthcare", "Buffalo NY",
                               found=10, passed=8, quality_score=score, db=db)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from database.orm_models import SourcePerformance

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 6.0


def evaluate_quality(companies: list[dict[str, Any]]) -> float:
    """Score a batch of companies 0.0–10.0 based on data completeness.

    Phone and email missing is expected and normal — many real businesses
    don't publish them. The score reflects what we have, not what's missing.
    """
    if not companies:
        return 0.0

    total = len(companies)
    with_website = sum(1 for c in companies if c.get("website"))
    with_city = sum(1 for c in companies if c.get("city"))
    with_phone = sum(1 for c in companies if c.get("phone"))

    score = (
        (with_website / total) * 5.0
        + (with_city / total) * 3.0
        + (with_phone / total) * 2.0
    )
    return round(score, 2)


def is_quality_sufficient(score: float) -> bool:
    """Return True when quality meets the threshold to proceed."""
    return score >= QUALITY_THRESHOLD


def update_source_performance(
    source_name: str,
    industry: str,
    location: str,
    found: int,
    passed: int,
    quality_score: float,
    db: Session,
) -> None:
    """Upsert source_performance row with results from one Scout run.

    This is the learning writeback — next Scout run reads this table to
    rank sources and try the best one first.
    """
    now = datetime.now(timezone.utc)

    existing = db.execute(
        __import__("sqlalchemy").select(SourcePerformance).where(
            SourcePerformance.source_name == source_name,
            SourcePerformance.industry == industry.lower(),
            SourcePerformance.location == location.lower(),
        )
    ).scalar_one_or_none()

    if existing:
        # Rolling average: (old_avg * old_runs + new_score) / (old_runs + 1)
        new_runs = existing.total_runs + 1
        new_avg = round(
            (existing.avg_quality_score * existing.total_runs + quality_score) / new_runs, 2
        )
        existing.total_runs = new_runs
        existing.total_leads_found += found
        existing.total_leads_passed += passed
        existing.avg_quality_score = new_avg
        existing.last_quality_score = quality_score
        existing.last_run_at = now
        existing.updated_at = now
    else:
        db.add(SourcePerformance(
            id=uuid.uuid4(),
            source_name=source_name,
            industry=industry.lower(),
            location=location.lower(),
            total_runs=1,
            total_leads_found=found,
            total_leads_passed=passed,
            avg_quality_score=quality_score,
            last_quality_score=quality_score,
            last_run_at=now,
            created_at=now,
            updated_at=now,
        ))

    db.commit()
    logger.info(
        "source_performance updated: source=%s industry=%s location=%s score=%.1f",
        source_name, industry, location, quality_score,
    )


def rank_sources(
    industry: str,
    location: str,
    available_sources: list[str],
    db: Session,
) -> list[str]:
    """Return available_sources sorted by avg_quality_score for this context.

    Sources with no history keep their original order (no data = neutral).
    Sources with known good performance move to the front.
    """
    from sqlalchemy import select as sa_select

    rows = db.execute(
        sa_select(SourcePerformance).where(
            SourcePerformance.industry == industry.lower(),
            SourcePerformance.location == location.lower(),
            SourcePerformance.source_name.in_(available_sources),
        )
    ).scalars().all()

    known_scores = {row.source_name: row.avg_quality_score for row in rows}

    # Sources with history sorted desc, unknowns appended in original order
    known = sorted(
        [s for s in available_sources if s in known_scores],
        key=lambda s: known_scores[s],
        reverse=True,
    )
    unknown = [s for s in available_sources if s not in known_scores]
    return known + unknown
