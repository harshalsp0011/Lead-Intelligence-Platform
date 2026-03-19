from __future__ import annotations

"""Yelp Business Search API client for the Scout agent.

Purpose:
- Searches Yelp for businesses matching an industry and location.
- Returns normalized company dicts ready for duplicate checking and saving.
- Yelp does not reliably return a business website — the url field is the
  Yelp listing page, not the company's own site. We store it as source_url
  and leave website as None when the business site is unavailable.
- Phone is optional — stored as None when absent.

Dependencies:
- YELP_API_KEY in .env
- requests

Usage:
    from agents.scout.yelp_client import search_companies
    companies = search_companies("healthcare", "Buffalo NY", limit=50)
"""

import logging
from typing import Any, Optional

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

_YELP_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"

# Maps Yelp category aliases to our industry buckets
_CATEGORY_MAP = {
    "health": "healthcare",
    "hospitals": "healthcare",
    "physicians": "healthcare",
    "dentists": "healthcare",
    "pharmacy": "healthcare",
    "optometrists": "healthcare",
    "physicaltherapy": "healthcare",
    "hotels": "hospitality",
    "hotelstravel": "hospitality",
    "restaurants": "hospitality",
    "food": "hospitality",
    "shopping": "retail",
    "fashion": "retail",
    "retail": "retail",
    "education": "public_sector",
    "publicservicesgovt": "public_sector",
    "manufacturing": "manufacturing",
    "professional": "office",
    "officespaces": "office",
}

# Yelp category terms to pass per industry
_INDUSTRY_TERMS = {
    "healthcare": "health medical clinic hospital",
    "hospitality": "hotel lodging",
    "manufacturing": "manufacturing industrial",
    "retail": "retail shopping",
    "public_sector": "government education school",
    "office": "office professional services",
}


def search_companies(industry: str, location: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search Yelp for businesses in an industry and location.

    Returns a list of normalized company dicts. Website and phone may be None
    — that is expected and handled gracefully downstream.

    Args:
        industry: e.g. 'healthcare', 'hospitality', 'manufacturing'
        location: e.g. 'Buffalo NY', 'Chicago IL'
        limit: max results (Yelp free tier max is 50 per request)
    """
    settings = get_settings()
    api_key = getattr(settings, "YELP_API_KEY", "")
    if not api_key:
        logger.warning("YELP_API_KEY not set — skipping Yelp source")
        return []

    search_term = _INDUSTRY_TERMS.get(industry.lower(), industry)

    params = {
        "term": search_term,
        "location": location,
        "limit": min(limit, 50),
        "sort_by": "rating",
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(_YELP_SEARCH_URL, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Yelp API call failed: %s", exc)
        return []

    businesses = data.get("businesses") or []
    companies: list[dict[str, Any]] = []

    for biz in businesses:
        # Skip permanently closed businesses
        if biz.get("is_closed"):
            continue

        name = (biz.get("name") or "").strip()
        if not name:
            continue

        # Yelp url is the Yelp listing page — use as source_url, not company website
        yelp_url = biz.get("url") or ""
        # Phone: optional — Yelp returns "" when not available
        phone = biz.get("display_phone") or biz.get("phone") or None
        if phone == "":
            phone = None

        location_data = biz.get("location") or {}
        city = location_data.get("city") or None
        state = location_data.get("state") or None

        categories = biz.get("categories") or []
        mapped_industry = _map_industry(categories, industry)

        companies.append({
            "name": name,
            "website": None,          # Yelp does not return the business website
            "phone": phone,           # optional, None when not listed
            "city": city,
            "state": state,
            "industry": mapped_industry,
            "source": "yelp",
            "source_url": yelp_url,
        })

    logger.info("Yelp returned %d companies for '%s' in '%s'", len(companies), industry, location)
    return companies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_industry(categories: list[dict], fallback_industry: str) -> str:
    """Map Yelp category aliases to our industry bucket."""
    for cat in categories:
        alias = (cat.get("alias") or "").lower()
        for keyword, bucket in _CATEGORY_MAP.items():
            if keyword in alias:
                return bucket
    return fallback_industry.lower()
