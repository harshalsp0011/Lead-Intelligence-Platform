from __future__ import annotations

"""Scout search-provider client.

Purpose:
- Discover additional directory/listing URLs when static sources are exhausted.

Dependencies:
- requests
- config.settings

Usage:
- Called by scout_agent.decide_next_source for dynamic fallback discovery.
"""

import logging
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from agents.scout import directory_scraper
from config.settings import get_settings

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Sites that require login, have paywalls, or actively block scrapers.
# Tavily often returns these as "directory" sources but they can never be scraped.
# Skipping them saves 60-90 seconds of wasted HTTP retries per scout run.
_UNSCRAPPABLE_DOMAINS = {
    "glassdoor.com",
    "linkedin.com",
    "zoominfo.com",
    "seamless.ai",
    "bizjournals.com",
    "bizbuysell.com",
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "yelp.com",         # Yelp is called via API in Phase 3, not scraped
    "indeed.com",
    "ziprecruiter.com",
    "monster.com",
    "crunchbase.com",
    "dnb.com",
    "manta.com",
    "hoovers.com",
    "apollo.io",
    "lusha.com",
    "rocketreach.co",
    "f6s.com",
    "youtube.com",
    "amazon.com",
    "wikipedia.org",
}


@lru_cache(maxsize=64)
def _cached_tavily_search(industry: str, location: str) -> tuple[dict[str, Any], ...]:
    settings = get_settings()
    provider = str(settings.SEARCH_PROVIDER or "").strip().lower()
    api_key = str(settings.TAVILY_API_KEY or "").strip()

    if provider != "tavily" or not api_key:
        return tuple()

    queries = [
        f"{industry} companies directory in {location}",
        f"{industry} business association members {location}",
        f"top {industry} employers {location}",
    ]

    seen_urls: set[str] = set()
    discovered: list[dict[str, Any]] = []

    for query in queries:
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 10,
        }
        try:
            response = requests.post(
                _TAVILY_SEARCH_URL,
                json=payload,
                timeout=settings.SCRAPER_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            logger.warning("Tavily search request failed for query '%s': %s", query, exc)
            continue

        for item in body.get("results", []):
            url = str(item.get("url", "")).strip()
            title = str(item.get("title", "")).strip()
            if not url or not url.startswith(("http://", "https://")):
                continue

            parsed = urlparse(url)
            if not parsed.netloc:
                continue

            # Keep each URL once per search run.
            normalized_url = url.rstrip("/")
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            host = parsed.netloc.lower().removeprefix("www.")

            # Skip sites that require login, paywall, or block scrapers entirely.
            # These are never scrapable and only waste time.
            if any(host.endswith(blocked) for blocked in _UNSCRAPPABLE_DOMAINS):
                logger.debug("Skipping blocked domain: %s", host)
                continue

            source_name = f"tavily:{host}:{len(discovered) + 1}"
            discovered.append(
                {
                    "name": source_name,
                    "url": normalized_url,
                    "category": industry,
                    "location": location,
                    "active": True,
                    "notes": title,
                }
            )

    return tuple(discovered)


def search_directory_sources(
    industry: str,
    location: str,
    db_session: Session | None = None,
) -> list[dict[str, Any]]:
    """Return discovered dynamic sources from the configured search provider."""
    normalized_industry = (industry or "").strip().lower()
    normalized_location = (location or "").strip().lower()

    if not normalized_industry and not normalized_location:
        return []

    discovered = list(_cached_tavily_search(normalized_industry, normalized_location))

    if db_session is not None and discovered:
        try:
            directory_scraper.save_directory_sources(discovered, db_session, discovered_via="tavily")
        except Exception as exc:
            logger.warning("Could not save Tavily sources to DB: %s", exc)

    return discovered
