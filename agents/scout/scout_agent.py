from __future__ import annotations

"""Main Scout agent coordinator.

This module orchestrates source selection, scraping, extraction, enrichment,
and persistence for company discovery workflows.

Source priority order (ranked by source_performance history when available):
  1. directory_scraper  — configured DB sources (Yellow Pages etc.)
  2. tavily             — AI-powered search fallback
  3. google_maps        — Google Places API
  4. yelp               — Yelp Business Search API

After every source attempt the Scout Critic evaluates quality.
If quality is insufficient and target count not met, the next source is tried.
After the full run, source_performance is updated for every source attempted.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from agents.scout import company_extractor, directory_scraper, search_client, website_crawler
from agents.scout.scout_critic import (
    evaluate_quality,
    is_quality_sufficient,
    rank_sources,
    update_source_performance,
)
from database.orm_models import AgentRunLog, Company

logger = logging.getLogger(__name__)


def _log_progress(db: Session, run_id: str | None, message: str) -> None:
    """Write a human-readable progress step to agent_run_logs for live UI display."""
    if not run_id:
        return
    try:
        entry = AgentRunLog(
            id=uuid.uuid4(),
            run_id=uuid.UUID(run_id),
            agent="scout",
            action="progress",
            status="info",
            output_summary=message,
            logged_at=datetime.now(timezone.utc),
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Failed to write progress log: %s", message)

_KNOWN_INDUSTRIES = {
    "healthcare",
    "hospitality",
    "manufacturing",
    "retail",
    "public_sector",
    "office",
}

# All API source names in default order (overridden by source_performance history)
_API_SOURCES = ["google_maps", "yelp"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    industry: str,
    location: str,
    count: int,
    db_session: Session,
    run_id: str | None = None,
) -> list[str]:
    """Run Scout and return newly saved company IDs.

    Tries sources in performance-ranked order. After each source the Critic
    checks quality and count. Stops when target reached or all sources used.
    Writes source_performance after every attempt for learning.
    """
    saved_ids: list[str] = []
    used_sources: list[str] = []
    source_results: list[dict] = []  # tracks (source, found, passed, score) for writeback

    _log_progress(db_session, run_id, f"Starting Scout — looking for {count} {industry} companies in {location}")

    # Rank API sources by past performance for this context
    ranked_api_sources = rank_sources(industry, location, _API_SOURCES, db_session)

    # --- Phase 1: configured directory sources ---
    dir_sources = directory_scraper.load_directory_sources(db_session)
    if dir_sources:
        _log_progress(db_session, run_id, f"Checking {len(dir_sources)} configured directory source(s)...")
    for source in dir_sources:
        if len(saved_ids) >= count:
            break

        source_name = str(source.get("name", "")).strip()
        if source_name.lower() in {s.lower() for s in used_sources}:
            continue

        _log_progress(db_session, run_id, f"Scraping directory: {source_name}...")
        used_sources.append(source_name)
        try:
            batch = _scrape_and_save_directory(source, db_session, run_id)
        except Exception:
            logger.exception("Directory source failed: %s", source_name)
            _log_progress(db_session, run_id, f"Directory {source_name} failed — skipping")
            source_results.append({"source": source_name, "found": 0, "passed": 0, "score": 0.0})
            continue

        score = evaluate_quality(batch)
        passed = len(batch)
        source_results.append({"source": source_name, "found": len(batch), "passed": passed, "score": score})

        if batch:
            remaining = count - len(saved_ids)
            new_ids = _save_api_companies(batch, db_session, run_id)
            saved_ids.extend(new_ids[:remaining])
            _log_progress(db_session, run_id, f"Found {len(new_ids)} companies from {source_name} (total: {len(saved_ids)})")

        logger.info("Directory source %s: found=%d score=%.1f total_saved=%d",
                    source_name, len(batch), score, len(saved_ids))

    # --- Phase 2: Tavily dynamic search ---
    if len(saved_ids) < count:
        _log_progress(db_session, run_id, f"Searching Tavily for {industry} directories in {location}...")
        tavily_sources = search_client.search_directory_sources(industry, location, db_session)
        for source in tavily_sources:
            if len(saved_ids) >= count:
                break
            source_name = str(source.get("name", "")).strip()
            if source_name.lower() in {s.lower() for s in used_sources}:
                continue

            _log_progress(db_session, run_id, f"Scraping Tavily result: {source_name}...")
            used_sources.append(source_name)
            try:
                batch = _scrape_and_save_directory(source, db_session, run_id)
            except Exception:
                logger.exception("Tavily source failed: %s", source_name)
                _log_progress(db_session, run_id, f"Tavily source {source_name} failed — skipping")
                source_results.append({"source": "tavily", "found": 0, "passed": 0, "score": 0.0})
                continue

            score = evaluate_quality(batch)
            source_results.append({"source": "tavily", "found": len(batch), "passed": len(batch), "score": score})

            if batch:
                remaining = count - len(saved_ids)
                new_ids = _save_api_companies(batch, db_session, run_id)
                saved_ids.extend(new_ids[:remaining])
                _log_progress(db_session, run_id, f"Found {len(new_ids)} companies via Tavily/{source_name} (total: {len(saved_ids)})")

            logger.info("Tavily source %s: found=%d score=%.1f total_saved=%d",
                        source_name, len(batch), score, len(saved_ids))

    # --- Phase 3: API sources (Google Maps, Yelp) in ranked order ---
    for api_source in ranked_api_sources:
        if len(saved_ids) >= count:
            break
        if api_source in {s.lower() for s in used_sources}:
            continue

        source_label = "Google Maps" if api_source == "google_maps" else "Yelp"
        _log_progress(db_session, run_id, f"Trying {source_label} for {industry} in {location}...")
        used_sources.append(api_source)
        remaining = count - len(saved_ids)

        try:
            batch = _fetch_from_api_source(api_source, industry, location, limit=max(remaining + 5, 20))
        except Exception:
            logger.exception("API source failed: %s", api_source)
            _log_progress(db_session, run_id, f"{source_label} failed — skipping")
            source_results.append({"source": api_source, "found": 0, "passed": 0, "score": 0.0})
            continue

        if not batch:
            _log_progress(db_session, run_id, f"{source_label} returned 0 results")
            source_results.append({"source": api_source, "found": 0, "passed": 0, "score": 0.0})
            continue

        score = evaluate_quality(batch)
        new_ids = _save_api_companies(batch, db_session, run_id)
        source_results.append({"source": api_source, "found": len(batch), "passed": len(new_ids), "score": score})
        saved_ids.extend(new_ids[:remaining])

        _log_progress(db_session, run_id, f"Found {len(new_ids)} companies from {source_label} (total: {len(saved_ids)})")
        sufficient = is_quality_sufficient(score)
        logger.info(
            "API source %s: found=%d saved=%d score=%.1f sufficient=%s total_saved=%d",
            api_source, len(batch), len(new_ids), score, sufficient, len(saved_ids),
        )

    # --- Write source_performance for every source tried ---
    for result in source_results:
        update_source_performance(
            source_name=result["source"],
            industry=industry,
            location=location,
            found=result["found"],
            passed=result["passed"],
            quality_score=result["score"],
            db=db_session,
        )

    _log_progress(db_session, run_id, f"Scout complete — saved {len(saved_ids)} of {count} requested companies")
    logger.info(
        "Scout complete: saved=%d target=%d industry=%s location=%s sources_tried=%s",
        len(saved_ids), count, industry, location, used_sources,
    )
    return saved_ids


# ---------------------------------------------------------------------------
# Directory source helpers
# ---------------------------------------------------------------------------

def _scrape_and_save_directory(source_dict: dict[str, Any], db_session: Session, run_id: str | None) -> list[dict]:
    """Scrape one directory source, returning valid non-duplicate company dicts."""
    source_url = str(source_dict.get("url", "")).strip()
    if not source_url:
        return []

    raw_companies = directory_scraper.scrape_directory(source_url)
    source_category = str(source_dict.get("category", "")).strip().lower()
    valid_companies: list[dict] = []

    for raw in raw_companies:
        raw_html = str(raw.get("raw_html", ""))
        raw_text = " ".join(str(raw.get(k, "")) for k in ("name", "website", "category", "city")).strip()

        cleaned = company_extractor.extract_all_fields(raw_html, raw_text)
        industry = company_extractor.classify_industry(cleaned.get("category"))

        if industry == "unknown":
            source_industry = company_extractor.classify_industry(source_category)
            if source_industry != "unknown":
                industry = source_industry
            elif source_category in _KNOWN_INDUSTRIES:
                industry = source_category

        if industry == "unknown":
            continue

        cleaned["industry"] = industry
        cleaned["source"] = source_dict.get("name")
        cleaned["source_url"] = source_url

        # Duplicate check: by website domain first, then name+city
        if company_extractor.check_duplicate(
            cleaned.get("website"),
            db_session,
            name=cleaned.get("name"),
            city=cleaned.get("city"),
        ):
            continue

        if not _validate_scraped(cleaned):
            continue

        crawl_signals = website_crawler.crawl_company_site(cleaned.get("website") or "")
        cleaned.update({
            "location_count": crawl_signals.get("location_count"),
            "employee_signal": crawl_signals.get("employee_signal"),
            "facility_type": crawl_signals.get("facility_type"),
        })
        valid_companies.append(cleaned)

    return valid_companies


def _validate_scraped(company: dict) -> bool:
    """Scraped companies must have name, website, known industry, and reachable site."""
    name = str(company.get("name", "")).strip()
    website = str(company.get("website", "")).strip()
    industry = str(company.get("industry", "unknown")).strip().lower()

    if not name or not website or industry == "unknown":
        return False
    return website_crawler.is_site_reachable(website)


# ---------------------------------------------------------------------------
# API source helpers
# ---------------------------------------------------------------------------

def _fetch_from_api_source(source: str, industry: str, location: str, limit: int) -> list[dict]:
    """Dispatch to the right API client based on source name."""
    if source == "google_maps":
        from agents.scout.google_maps_client import search_companies
        return search_companies(industry, location, limit=limit)
    if source == "yelp":
        from agents.scout.yelp_client import search_companies
        return search_companies(industry, location, limit=limit)
    return []


def _save_api_companies(
    companies: list[dict[str, Any]],
    db_session: Session,
    run_id: str | None,
) -> list[str]:
    """Save API-sourced companies to DB. Skips duplicates silently.

    API sources (Google Maps, Yelp) are considered high quality — we do NOT
    require a website to save them. Phone and email missing is normal.
    We only require: name + industry + city.
    """
    saved_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for company in companies:
        name = str(company.get("name", "")).strip()
        industry = str(company.get("industry", "")).strip().lower()
        city = str(company.get("city") or "").strip()

        # Minimum fields for API companies — website and phone are optional
        if not name or not industry or industry == "unknown":
            continue

        # Duplicate check using improved check_duplicate (domain + name+city)
        if company_extractor.check_duplicate(
            company.get("website"),
            db_session,
            name=name,
            city=city or None,
        ):
            continue

        # employee_count and site_count: prefer pre-crawled signals (directory path),
        # otherwise crawl the website now if we have one (Google Maps / Yelp path).
        raw_emp = company.get("employee_count") or company.get("employee_signal")
        raw_sites = company.get("site_count") or company.get("location_count")

        website_val = company.get("website") or None
        if website_val and (not raw_emp or not raw_sites):
            try:
                crawl = website_crawler.crawl_company_site(website_val)
                raw_emp = raw_emp or crawl.get("employee_signal")
                raw_sites = raw_sites or crawl.get("location_count")
            except Exception:
                pass  # crawl failure is non-fatal — score with whatever we have

        emp_count = int(raw_emp) if raw_emp else None
        site_count = int(raw_sites) if raw_sites else None

        try:
            row = Company(
                id=uuid.uuid4(),
                name=name,
                website=company.get("website") or None,
                industry=industry,
                city=city or None,
                state=company_extractor.normalize_state(company.get("state")),
                employee_count=emp_count,
                site_count=site_count,
                source=company.get("source"),
                source_url=company.get("source_url"),
                run_id=uuid.UUID(run_id) if run_id else None,
                quality_score=None,  # set by Critic after batch evaluation
                status="new",
                date_found=now,
                created_at=now,
                updated_at=now,
            )
            db_session.add(row)
            db_session.flush()
            db_session.commit()
            saved_ids.append(str(row.id))
        except Exception:
            db_session.rollback()
            logger.exception("Failed to save company: %s", name)

    return saved_ids
