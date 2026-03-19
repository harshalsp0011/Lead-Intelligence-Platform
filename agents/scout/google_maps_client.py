from __future__ import annotations

"""Google Maps Places API client for the Scout agent.

Purpose:
- Searches Google Places for businesses matching an industry and location.
- Returns normalized company dicts ready for duplicate checking and saving.
- Phone and website are optional — many real businesses don't have both.
  Missing fields are stored as None; nothing fails because of absent contact info.

Dependencies:
- GOOGLE_MAPS_API_KEY in .env
- requests

Usage:
    from agents.scout.google_maps_client import search_companies
    companies = search_companies("healthcare", "Buffalo NY", limit=20)
"""

import logging
from typing import Any, Optional

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.displayName,"
    "places.formattedAddress,"
    "places.websiteUri,"
    "places.nationalPhoneNumber,"
    "places.primaryTypeDisplayName,"
    "places.businessStatus"
)

# Maps Google place types to our industry buckets
_TYPE_MAP = {
    "hospital": "healthcare",
    "doctor": "healthcare",
    "dentist": "healthcare",
    "health": "healthcare",
    "medical": "healthcare",
    "pharmacy": "healthcare",
    "physiotherapist": "healthcare",
    "lodging": "hospitality",
    "hotel": "hospitality",
    "motel": "hospitality",
    "restaurant": "hospitality",
    "food": "hospitality",
    "store": "retail",
    "shop": "retail",
    "retail": "retail",
    "school": "public_sector",
    "university": "public_sector",
    "government": "public_sector",
    "factory": "manufacturing",
    "manufacturer": "manufacturing",
    "office": "office",
}


def search_companies(industry: str, location: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search Google Places for businesses in an industry and location.

    Returns a list of normalized company dicts. Phone and website may be None
    — that is expected and handled gracefully downstream.

    Args:
        industry: e.g. 'healthcare', 'hospitality', 'manufacturing'
        location: e.g. 'Buffalo NY', 'Chicago IL'
        limit: max results to return (Google max is 20 per request)
    """
    settings = get_settings()
    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_MAPS_API_KEY not set — skipping Google Maps source")
        return []

    query = f"{industry} businesses in {location}"
    payload = {
        "textQuery": query,
        "maxResultCount": min(limit, 20),
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    try:
        response = requests.post(_PLACES_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Google Maps API call failed: %s", exc)
        return []

    places = data.get("places") or []
    companies: list[dict[str, Any]] = []

    for place in places:
        # Skip permanently closed businesses
        if place.get("businessStatus") == "CLOSED_PERMANENTLY":
            continue

        name = _extract_display_name(place)
        if not name:
            continue

        website = place.get("websiteUri") or None
        # Phone is optional — many businesses don't list it publicly
        phone = place.get("nationalPhoneNumber") or None
        address = place.get("formattedAddress") or ""
        city, state = _parse_city_state(address)
        raw_type = _extract_type_label(place)
        mapped_industry = _map_industry(raw_type, industry)

        companies.append({
            "name": name,
            "website": website,
            "phone": phone,
            "city": city,
            "state": state,
            "industry": mapped_industry,
            "source": "google_maps",
            "source_url": f"https://maps.google.com/?q={name.replace(' ', '+')}",
        })

    logger.info("Google Maps returned %d companies for '%s' in '%s'", len(companies), industry, location)
    return companies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_display_name(place: dict) -> Optional[str]:
    name_field = place.get("displayName")
    if isinstance(name_field, dict):
        return name_field.get("text") or None
    return str(name_field).strip() if name_field else None


def _extract_type_label(place: dict) -> str:
    type_field = place.get("primaryTypeDisplayName")
    if isinstance(type_field, dict):
        return type_field.get("text") or ""
    return str(type_field or "").lower()


def _map_industry(raw_type: str, fallback_industry: str) -> str:
    raw_lower = raw_type.lower()
    for keyword, bucket in _TYPE_MAP.items():
        if keyword in raw_lower:
            return bucket
    # Fall back to the industry the user searched for
    return fallback_industry.lower()


def _parse_city_state(formatted_address: str) -> tuple[Optional[str], Optional[str]]:
    """Extract city and state from a Google formatted address string.

    Google format: "123 Main St, Buffalo, NY 14201, USA"
    """
    if not formatted_address:
        return None, None

    parts = [p.strip() for p in formatted_address.split(",")]
    # Remove country (last part is usually "USA")
    if parts and parts[-1].strip().upper() in ("USA", "US", "UNITED STATES"):
        parts = parts[:-1]

    # State + zip is usually the last remaining part: "NY 14201"
    state: Optional[str] = None
    city: Optional[str] = None

    if len(parts) >= 2:
        state_zip = parts[-1].strip().split()
        if state_zip:
            state = state_zip[0].upper() if len(state_zip[0]) == 2 else None
        city = parts[-2].strip() if len(parts) >= 2 else None

    return city, state
