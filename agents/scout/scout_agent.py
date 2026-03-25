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

from agents.scout import company_extractor, directory_scraper, llm_deduplicator, llm_query_planner, news_scout_client, search_client, website_crawler
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

    # --- Agentic query planning: LLM generates 3–5 diverse search queries ---
    _log_progress(db_session, run_id, "Planning search queries...")
    planned_queries = llm_query_planner.plan_queries(industry, location)
    _log_progress(db_session, run_id, f"LLM generated {len(planned_queries)} search variants: {planned_queries[0]!r}...")
    logger.info("[scout] Planned queries: %s", planned_queries)

    # Rank API sources by past performance for this context
    ranked_api_sources = rank_sources(industry, location, _API_SOURCES, db_session)

    # --- Phase 0: News-based intent scout ---
    # Finds companies IN THE NEWS with buying signals (expansion, cost pressure, new facility).
    # These are the warmest leads — a specific reason they need an audit RIGHT NOW.
    # Runs first so intent-signal companies are prioritised and saved before generic results.
    # Agentic concept: Intent-Based Prospecting
    _log_progress(db_session, run_id, "Scanning local business news for buying signals...")
    try:
        news_companies = news_scout_client.find_companies_in_news(
            industry, location, max_results=max(count, 5)
        )
        if news_companies:
            _log_progress(
                db_session, run_id,
                f"News scout found {len(news_companies)} companies with buying signals "
                f"(expansion, cost pressure, new facility)"
            )
            remaining_before_news = count - len(saved_ids)
            news_ids = _save_news_companies(news_companies, db_session, run_id, max_save=remaining_before_news)
            saved_ids.extend(news_ids)
            source_results.append({
                "source": "news_scout",
                "found": len(news_companies),
                "passed": len(news_ids),
                "score": evaluate_quality(news_companies),
            })
            _log_progress(
                db_session, run_id,
                f"Saved {len(news_ids)} intent-signal companies from news (total: {len(saved_ids)})"
            )
        else:
            _log_progress(db_session, run_id, "No news signals found — continuing with directory search")
    except Exception as exc:
        logger.warning("[scout] News scout failed (non-fatal): %s", exc)
        _log_progress(db_session, run_id, "News scout skipped — continuing with directory search")

    # --- Phase 1: configured directory sources (location-filtered) ---
    # Only try directory sources whose name contains a word from the target location.
    # This prevents Buffalo-specific sources from being tried for Rochester, Chicago, etc.
    # Sources that don't mention the location are almost guaranteed to fail and waste time.
    all_dir_sources = directory_scraper.load_directory_sources(db_session)
    location_words = {w.lower() for w in location.lower().split() if len(w) > 2}
    dir_sources = [
        s for s in all_dir_sources
        if any(w in str(s.get("name", "")).lower() for w in location_words)
    ]
    if all_dir_sources and not dir_sources:
        _log_progress(
            db_session, run_id,
            f"Skipping {len(all_dir_sources)} directory sources — none match location '{location}'. "
            "Going straight to Tavily + Google Maps."
        )
    elif dir_sources:
        _log_progress(db_session, run_id, f"Checking {len(dir_sources)} directory source(s) for {location}...")
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

    # --- Phase 2: Tavily — use LLM-planned queries instead of hardcoded strings ---
    if len(saved_ids) < count:
        _log_progress(db_session, run_id, f"Searching Tavily with {len(planned_queries)} query variants...")
        tavily_sources = search_client.search_with_queries(planned_queries, location, db_session)

        if not tavily_sources:
            # Fallback to old behavior if search_with_queries returns nothing (e.g. Tavily not configured)
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

    # --- Phase 3: API sources — run ALL planned query variants per source ---
    api_batch_all: list[dict] = []  # collected across all variants before dedup

    for api_source in ranked_api_sources:
        if len(saved_ids) >= count:
            break
        if api_source in {s.lower() for s in used_sources}:
            continue

        source_label = "Google Maps" if api_source == "google_maps" else "Yelp"
        used_sources.append(api_source)
        remaining = count - len(saved_ids)
        per_query_limit = max((remaining + 5) // len(planned_queries), 10)

        _log_progress(
            db_session, run_id,
            f"Searching {source_label} with {len(planned_queries)} query variants..."
        )

        source_found = 0
        for q_idx, query_text in enumerate(planned_queries):
            try:
                batch = _fetch_from_api_source(
                    api_source, industry, location,
                    limit=per_query_limit,
                    query_text=query_text,
                )
                if batch:
                    api_batch_all.extend(batch)
                    source_found += len(batch)
                    logger.info(
                        "[scout] %s query %d/%d '%s': %d results",
                        source_label, q_idx + 1, len(planned_queries), query_text, len(batch),
                    )
            except Exception:
                logger.exception("API source failed: %s query=%s", api_source, query_text)

        _log_progress(
            db_session, run_id,
            f"{source_label}: collected {source_found} raw results across {len(planned_queries)} queries"
        )
        source_results.append({
            "source": api_source,
            "found": source_found,
            "passed": source_found,
            "score": evaluate_quality(api_batch_all) if api_batch_all else 0.0,
        })

    # --- LLM Deduplication: remove near-duplicates from the API batch ---
    if api_batch_all:
        _log_progress(db_session, run_id, f"Deduplicating {len(api_batch_all)} collected companies...")
        api_batch_deduped = llm_deduplicator.deduplicate(api_batch_all)
        removed = len(api_batch_all) - len(api_batch_deduped)
        if removed:
            _log_progress(db_session, run_id, f"Removed {removed} duplicate(s) — {len(api_batch_deduped)} unique companies")
        logger.info("[scout] Dedup: %d → %d companies", len(api_batch_all), len(api_batch_deduped))

        remaining = count - len(saved_ids)
        new_ids = _save_api_companies(api_batch_deduped, db_session, run_id, max_save=remaining)
        saved_ids.extend(new_ids)
        _log_progress(db_session, run_id, f"Saved {len(new_ids)} of {len(api_batch_deduped)} unique companies (target was {count}, total: {len(saved_ids)})")

    # --- Quality check: if < 80% of target found, retry with new LLM queries (once) ---
    if len(saved_ids) < int(count * 0.8):
        _log_progress(
            db_session, run_id,
            f"Quality check: only {len(saved_ids)}/{count} found — generating retry queries..."
        )
        retry_queries = llm_query_planner.plan_retry_queries(
            industry=industry,
            location=location,
            results_found=len(saved_ids),
            target=count,
            used_queries=planned_queries,
        )
        _log_progress(db_session, run_id, f"Retry: trying {len(retry_queries)} new query variants...")
        logger.info("[scout] Retry queries: %s", retry_queries)

        retry_batch: list[dict] = []
        for api_source in ranked_api_sources:
            per_query_limit = max(count - len(saved_ids) + 5, 10)
            for query_text in retry_queries:
                try:
                    batch = _fetch_from_api_source(
                        api_source, industry, location,
                        limit=per_query_limit,
                        query_text=query_text,
                    )
                    if batch:
                        retry_batch.extend(batch)
                except Exception:
                    logger.exception("Retry API source failed: %s query=%s", api_source, query_text)

        if retry_batch:
            retry_deduped = llm_deduplicator.deduplicate(retry_batch)
            remaining = count - len(saved_ids)
            retry_ids = _save_api_companies(retry_deduped, db_session, run_id, max_save=remaining)
            saved_ids.extend(retry_ids)
            _log_progress(
                db_session, run_id,
                f"Retry saved {len(retry_ids)} more companies (total: {len(saved_ids)})"
            )
            source_results.append({
                "source": "retry",
                "found": len(retry_batch),
                "passed": len(retry_ids),
                "score": evaluate_quality(retry_deduped),
            })

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


def _save_news_companies(
    companies: list[dict[str, Any]],
    db_session: Session,
    run_id: str | None,
    max_save: int | None = None,
) -> list[str]:
    """Save news-scout companies to DB with their intent_signal field.

    News companies come from article extraction — no website crawl needed,
    no industry validation required (LLM already classified them).
    Minimum required: name + industry.
    """
    saved_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for company in companies:
        if max_save is not None and len(saved_ids) >= max_save:
            break

        name = str(company.get("name", "")).strip()
        industry = str(company.get("industry", "")).strip().lower()
        if not name or not industry or industry == "unknown":
            continue

        city = str(company.get("city") or "").strip()

        # Skip if already in DB (same name + city, or same domain if website found)
        if company_extractor.check_duplicate(
            company.get("website"),
            db_session,
            name=name,
            city=city or None,
        ):
            continue

        try:
            row = Company(
                id=uuid.uuid4(),
                name=name,
                website=company.get("website") or None,
                phone=company.get("phone") or None,
                industry=industry,
                city=city or None,
                state=company_extractor.normalize_state(company.get("state")),
                source=company.get("source", "news_scout"),
                source_url=company.get("source_url") or None,
                intent_signal=company.get("intent_signal") or None,
                run_id=uuid.UUID(run_id) if run_id else None,
                status="new",
                date_found=now,
                created_at=now,
                updated_at=now,
            )
            db_session.add(row)
            db_session.flush()
            db_session.commit()
            saved_ids.append(str(row.id))
            logger.info(
                "[news_scout] Saved: %s | signal: %s",
                name, company.get("intent_signal", "")[:80],
            )
        except Exception:
            db_session.rollback()
            logger.exception("[news_scout] Failed to save company: %s", name)

    return saved_ids


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

def _fetch_from_api_source(
    source: str,
    industry: str,
    location: str,
    limit: int,
    query_text: str | None = None,
) -> list[dict]:
    """Dispatch to the right API client based on source name.

    query_text: optional LLM-planned query string. When provided, overrides
    the default query built inside each client.
    """
    if source == "google_maps":
        from agents.scout.google_maps_client import search_companies
        return search_companies(industry, location, limit=limit, query_text=query_text)
    if source == "yelp":
        from agents.scout.yelp_client import search_companies
        # Yelp uses term/category — query_text used as term override when provided
        return search_companies(industry, location, limit=limit)
    return []


def _save_api_companies(
    companies: list[dict[str, Any]],
    db_session: Session,
    run_id: str | None,
    max_save: int | None = None,
) -> list[str]:
    """Save API-sourced companies to DB. Skips duplicates silently.

    API sources (Google Maps, Yelp) are considered high quality — we do NOT
    require a website to save them. Phone and email missing is normal.
    We only require: name + industry + city.

    max_save: if set, stop saving after this many successful inserts.
              Prevents saving 44 when user asked for 10.
    """
    saved_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for company in companies:
        # Stop early if we've hit the requested count
        if max_save is not None and len(saved_ids) >= max_save:
            break

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
                phone=company.get("phone") or None,
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
