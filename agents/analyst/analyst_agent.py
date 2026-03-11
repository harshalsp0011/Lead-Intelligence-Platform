from __future__ import annotations

"""Main Analyst agent entry point.

This module coordinates analysis, scoring, and persistence for one company at a
time, and can batch-process a list of company IDs.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from agents.analyst import savings_calculator, score_engine, spend_calculator
from agents.scout import website_crawler

_DEREGULATED_STATES = {
    "NY",
    "TX",
    "IL",
    "OH",
    "PA",
    "NJ",
    "MA",
    "MD",
    "CT",
    "ME",
    "NH",
    "RI",
    "DE",
    "DC",
    "MI",
}


def run(company_ids: list[str], db_session: Session) -> list[str]:
    """Process a list of company IDs and return those scored successfully."""
    processed_ids: list[str] = []

    for company_id in company_ids:
        try:
            process_one_company(company_id, db_session)
            processed_ids.append(company_id)
        except Exception:
            db_session.rollback()

    return processed_ids


def process_one_company(company_id: str, db_session: Session) -> dict[str, Any]:
    """Run full analyst pipeline for one company and persist outputs."""
    row = db_session.execute(
        text(
            """
            SELECT
                id,
                name,
                website,
                industry,
                state,
                employee_count,
                site_count
            FROM companies
            WHERE id = :company_id
            """
        ),
        {"company_id": company_id},
    ).mappings().first()

    if row is None:
        raise ValueError(f"Company not found: {company_id}")

    company = dict(row)
    enriched = gather_company_data(company, db_session)

    site_count = int(enriched.get("site_count") or 1)
    employee_count = int(enriched.get("employee_count") or 0)
    industry = str(enriched.get("industry") or "unknown")
    state = str(enriched.get("state") or "")

    utility_spend = spend_calculator.calculate_utility_spend(site_count, industry, state)
    telecom_spend = spend_calculator.calculate_telecom_spend(employee_count, industry)
    total_spend = spend_calculator.calculate_total_spend(utility_spend, telecom_spend)

    savings = savings_calculator.calculate_all_savings(total_spend)
    savings_mid = float(savings["mid"])

    contact_found = _has_contact(company_id, db_session)
    data_quality_score = decide_data_quality(
        {
            "has_website": bool(enriched.get("has_website")),
            "has_locations_page": bool(enriched.get("has_locations_page")),
            "site_count": site_count,
            "employee_count": employee_count,
        },
        contact_found,
    )

    score = score_engine.compute_score(
        savings_mid=savings_mid,
        industry=industry,
        site_count=site_count,
        data_quality_score=data_quality_score,
    )
    tier = score_engine.assign_tier(score)
    score_reason = score_engine.generate_score_reason(
        industry=industry,
        site_count=site_count,
        savings_mid=savings_mid,
        data_quality_score=data_quality_score,
        deregulated_state=bool(enriched.get("deregulated_state")),
    )

    features_dict = {
        "estimated_site_count": site_count,
        "estimated_annual_utility_spend": utility_spend,
        "estimated_annual_telecom_spend": telecom_spend,
        "estimated_total_spend": total_spend,
        "savings_low": float(savings["low"]),
        "savings_mid": savings_mid,
        "savings_high": float(savings["high"]),
        "industry_fit_score": _score_industry_fit(industry),
        "multi_site_confirmed": site_count > 1,
        "deregulated_state": bool(enriched.get("deregulated_state")),
        "data_quality_score": data_quality_score,
    }

    save_features(company_id=company_id, features_dict=features_dict, db_session=db_session)
    save_score(
        company_id=company_id,
        score=score,
        tier=tier,
        score_reason=score_reason,
        db_session=db_session,
    )

    db_session.execute(
        text(
            """
            UPDATE companies
            SET status = 'scored',
                updated_at = NOW()
            WHERE id = :company_id
            """
        ),
        {"company_id": company_id},
    )
    db_session.commit()

    return {
        "company_id": company_id,
        "score": score,
        "tier": tier,
        "savings_mid": savings_mid,
    }


def gather_company_data(company: dict[str, Any], db_session: Session) -> dict[str, Any]:
    """Return company dict enriched with site/page/state scoring signals."""
    enriched = dict(company)

    website = str(enriched.get("website") or "").strip()
    current_site_count = int(enriched.get("site_count") or 0)
    current_employee_count = int(enriched.get("employee_count") or 0)

    crawl_result: dict[str, Any] = {
        "has_website": bool(website),
        "has_locations_page": False,
        "location_count": current_site_count,
        "employee_signal": current_employee_count,
    }

    if website and current_site_count <= 0:
        crawl_result = website_crawler.crawl_company_site(website)
        enriched["site_count"] = int(crawl_result.get("location_count") or 1)
        if current_employee_count <= 0:
            enriched["employee_count"] = int(crawl_result.get("employee_signal") or 0)

    enriched["has_website"] = bool(website)
    enriched["has_locations_page"] = bool(crawl_result.get("has_locations_page"))
    enriched["deregulated_state"] = check_deregulated_state(str(enriched.get("state") or ""))

    return enriched


def check_deregulated_state(state: str) -> bool:
    """Return True if the state is in the deregulated electricity list."""
    return (state or "").strip().upper() in _DEREGULATED_STATES


def save_features(company_id: str, features_dict: dict[str, Any], db_session: Session) -> str:
    """Insert company_features row and return new record UUID."""
    result = db_session.execute(
        text(
            """
            INSERT INTO company_features (
                company_id,
                estimated_sqft_per_site,
                estimated_site_count,
                estimated_annual_utility_spend,
                estimated_annual_telecom_spend,
                estimated_total_spend,
                savings_low,
                savings_mid,
                savings_high,
                industry_fit_score,
                multi_site_confirmed,
                deregulated_state,
                data_quality_score
            )
            VALUES (
                :company_id,
                :estimated_sqft_per_site,
                :estimated_site_count,
                :estimated_annual_utility_spend,
                :estimated_annual_telecom_spend,
                :estimated_total_spend,
                :savings_low,
                :savings_mid,
                :savings_high,
                :industry_fit_score,
                :multi_site_confirmed,
                :deregulated_state,
                :data_quality_score
            )
            RETURNING id
            """
        ),
        {
            "company_id": company_id,
            "estimated_sqft_per_site": features_dict.get("estimated_sqft_per_site"),
            "estimated_site_count": features_dict.get("estimated_site_count"),
            "estimated_annual_utility_spend": features_dict.get("estimated_annual_utility_spend"),
            "estimated_annual_telecom_spend": features_dict.get("estimated_annual_telecom_spend"),
            "estimated_total_spend": features_dict.get("estimated_total_spend"),
            "savings_low": features_dict.get("savings_low"),
            "savings_mid": features_dict.get("savings_mid"),
            "savings_high": features_dict.get("savings_high"),
            "industry_fit_score": features_dict.get("industry_fit_score"),
            "multi_site_confirmed": bool(features_dict.get("multi_site_confirmed")),
            "deregulated_state": bool(features_dict.get("deregulated_state")),
            "data_quality_score": features_dict.get("data_quality_score"),
        },
    )
    inserted_id = result.scalar_one()
    return str(inserted_id)


def save_score(
    company_id: str,
    score: float,
    tier: str,
    score_reason: str,
    db_session: Session,
) -> str:
    """Insert lead_scores row and return new record UUID."""
    result = db_session.execute(
        text(
            """
            INSERT INTO lead_scores (
                company_id,
                score,
                tier,
                score_reason,
                approved_human
            )
            VALUES (
                :company_id,
                :score,
                :tier,
                :score_reason,
                false
            )
            RETURNING id
            """
        ),
        {
            "company_id": company_id,
            "score": float(score),
            "tier": tier,
            "score_reason": score_reason,
        },
    )
    inserted_id = result.scalar_one()
    return str(inserted_id)


def decide_data_quality(crawl_result: dict[str, Any], contact_found: bool) -> float:
    """Calculate 0-10 quality signal from crawl and contact coverage."""
    return score_engine.assess_data_quality(
        site_count=int(crawl_result.get("site_count") or 0),
        employee_count=int(crawl_result.get("employee_count") or 0),
        has_website=bool(crawl_result.get("has_website")),
        has_locations_page=bool(crawl_result.get("has_locations_page")),
        has_contact_found=bool(contact_found),
    )


def _has_contact(company_id: str, db_session: Session) -> bool:
    result = db_session.execute(
        text(
            """
            SELECT 1
            FROM contacts
            WHERE company_id = :company_id
            LIMIT 1
            """
        ),
        {"company_id": company_id},
    )
    return result.first() is not None


def _score_industry_fit(industry: str) -> float:
    normalized = (industry or "").strip().lower()
    if normalized in {"healthcare", "hospitality", "manufacturing", "retail"}:
        return 10.0
    if normalized in {"public_sector", "office"}:
        return 7.0
    return 5.0