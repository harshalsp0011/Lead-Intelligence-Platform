from __future__ import annotations

"""Main Scout agent coordinator.

This module orchestrates source selection, scraping, extraction, enrichment,
and persistence for company discovery workflows.
"""

from importlib import import_module
import logging
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from agents.scout import company_extractor, directory_scraper, website_crawler

logger = logging.getLogger(__name__)

_KNOWN_INDUSTRIES = {
    "healthcare",
    "hospitality",
    "manufacturing",
    "retail",
    "public_sector",
    "office",
}


class ScoutState(TypedDict):
    industry: str
    location: str
    count: int
    db_session: Session
    saved_ids: list[str]
    used_sources: list[str]


def run(industry: str, location: str, count: int, db_session: Session) -> list[str]:
    """Run the Scout workflow and return newly saved company IDs."""
    state: ScoutState = {
        "industry": industry,
        "location": location,
        "count": count,
        "db_session": db_session,
        "saved_ids": [],
        "used_sources": [],
    }

    graph_module = import_module("langgraph.graph")
    state_graph = graph_module.StateGraph(ScoutState)

    def scout_loop(current_state: ScoutState) -> ScoutState:
        while len(current_state["saved_ids"]) < current_state["count"]:
            next_source = decide_next_source(
                current_state["industry"],
                current_state["location"],
                current_state["used_sources"],
            )
            if next_source is None:
                break

            current_state["used_sources"].append(str(next_source.get("name", "")))
            try:
                saved_from_source = scrape_and_save(next_source, current_state["db_session"])
            except Exception:
                logger.exception(
                    "Scout source failed; continuing to next source. source=%s url=%s",
                    next_source.get("name", ""),
                    next_source.get("url", ""),
                )
                continue

            if saved_from_source:
                remaining = current_state["count"] - len(current_state["saved_ids"])
                current_state["saved_ids"].extend(saved_from_source[:remaining])

        return current_state

    state_graph.add_node("scout_loop", scout_loop)
    state_graph.set_entry_point("scout_loop")
    state_graph.set_finish_point("scout_loop")

    app = state_graph.compile()
    final_state: ScoutState = app.invoke(state)

    log_scout_run(len(final_state["saved_ids"]), industry, location)
    return final_state["saved_ids"]


def scrape_and_save(source_dict: dict[str, Any], db_session: Session) -> list[str]:
    """Scrape one source and save valid, non-duplicate companies."""
    source_url = str(source_dict.get("url", "")).strip()
    if not source_url:
        return []

    raw_companies = directory_scraper.scrape_directory(source_url)
    source_category = str(source_dict.get("category", "")).strip().lower()
    saved_ids: list[str] = []

    for raw_company in raw_companies:
        raw_html = str(raw_company.get("raw_html", ""))
        raw_text = " ".join(
            str(raw_company.get(key, ""))
            for key in ("name", "website", "category", "city")
        ).strip()

        cleaned_company = company_extractor.extract_all_fields(raw_html, raw_text)
        industry = company_extractor.classify_industry(cleaned_company.get("category"))

        # Some directories do not expose per-listing categories. Fall back to
        # the source-level category so valid records are not dropped as unknown.
        if industry == "unknown":
            source_industry = company_extractor.classify_industry(source_category)
            if source_industry != "unknown":
                industry = source_industry
            elif source_category in _KNOWN_INDUSTRIES:
                industry = source_category

        cleaned_company["industry"] = industry

        website_url = str(cleaned_company.get("website") or "").strip()
        if company_extractor.check_duplicate(website_url, db_session):
            continue

        if cleaned_company["industry"] == "unknown":
            continue

        if not validate_company(cleaned_company):
            continue

        crawl_signals = website_crawler.crawl_company_site(cleaned_company.get("website") or "")

        company_payload = {
            **cleaned_company,
            "source": source_dict.get("name"),
            "source_url": source_url,
            "location_count": crawl_signals.get("location_count"),
            "employee_signal": crawl_signals.get("employee_signal"),
            "facility_type": crawl_signals.get("facility_type"),
        }

        inserted_id = company_extractor.save_to_database(company_payload, db_session)
        saved_ids.append(inserted_id)

    return saved_ids


def validate_company(raw_company_dict: dict[str, Any]) -> bool:
    """Return True if a company record meets minimum save criteria."""
    name = str(raw_company_dict.get("name", "")).strip()
    website = str(raw_company_dict.get("website", "")).strip()
    industry = str(raw_company_dict.get("industry", "unknown")).strip().lower()

    if not name:
        return False
    if not website:
        return False
    if industry == "unknown":
        return False

    return website_crawler.is_site_reachable(website)


def decide_next_source(industry: str, location: str, used_sources: list[str]) -> dict[str, Any] | None:
    """Return the next eligible active source, or None when exhausted."""
    sources = directory_scraper.load_directory_sources()

    target_industry = industry.strip().lower()
    target_location = location.strip().lower()
    used_names = {name.strip().lower() for name in used_sources}

    for source in sources:
        source_name = str(source.get("name", "")).strip()
        source_category = str(source.get("category", "")).strip().lower()
        source_location = str(source.get("location", "")).strip().lower()

        if source_name.lower() in used_names:
            continue

        industry_match = (
            not target_industry
            or target_industry in source_category
            or source_category in target_industry
            or source_category in {"business", "major_employers", "all"}
        )
        location_match = (
            not target_location
            or target_location in source_location
            or source_location in target_location
        )

        if industry_match and location_match:
            return source

    return None


def log_scout_run(count_found: int, industry: str, location: str) -> None:
    """Print a summary line for a completed Scout run."""
    print(f"Scout complete: found {count_found} companies in {industry} / {location}")
