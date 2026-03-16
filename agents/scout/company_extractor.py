from __future__ import annotations

"""Company extraction and cleanup helpers for the Scout agent.

This file turns raw directory HTML into cleaned company fields, normalizes data
like state and phone number, checks whether a company already exists, and saves
new company records into the `companies` table.
"""

import re
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.orm_models import Company

_PHONE_REGEX = re.compile(r"(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})")
_URL_REGEX = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_CITY_STATE_REGEX = re.compile(
    r"\b(?P<city>[A-Za-z][A-Za-z .'-]+?),\s*(?P<state>[A-Za-z]{2}|[A-Za-z][A-Za-z ]+)\b"
)

_STATE_MAP = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "dc": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
_STATE_MAP.update({code: code for code in _STATE_MAP.values()})


def extract_all_fields(raw_html: str, raw_text: str) -> dict[str, Optional[str]]:
    """Extract common company fields from raw listing HTML and text."""
    soup = BeautifulSoup(raw_html or "", "html.parser")

    name = _extract_name(soup, raw_text)
    website = _extract_website(soup, raw_text)
    category = _extract_category(soup, raw_text)
    phone = _extract_phone(soup, raw_text)
    city, state = _extract_city_state(soup, raw_text)

    return {
        "name": name,
        "website": website,
        "category": category,
        "city": city,
        "state": state,
        "phone": phone,
    }


def classify_industry(raw_category: Optional[str]) -> str:
    """Map a raw category string to a standard industry bucket."""
    if not raw_category:
        return "unknown"

    category = raw_category.lower()

    mappings = {
        "healthcare": ("health", "hospital", "medical", "clinic", "physician", "care"),
        "hospitality": ("lodging", "travel", "hospitality", "hotel", "motel", "tourism", "restaurant"),
        "manufacturing": ("manufactur", "industrial", "factory", "fabricat", "production"),
        "retail": ("retail", "store", "shop", "merchant", "ecommerce"),
        "public_sector": ("government", "public", "municipal", "county", "state agency", "education", "school", "university"),
        "office": ("office", "professional", "administrative", "corporate", "business services", "headquarters"),
    }

    for bucket, keywords in mappings.items():
        if any(keyword in category for keyword in keywords):
            return bucket

    return "unknown"


def extract_domain(website_url: Optional[str]) -> Optional[str]:
    """Return the normalized domain from a full website URL."""
    if not website_url:
        return None

    candidate = website_url.strip()
    if not candidate:
        return None

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    domain = (parsed.netloc or parsed.path).lower().strip()
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0]

    return domain or None


def check_duplicate(website_url: Optional[str], db_session: Session) -> bool:
    """Return True if a company with the same normalized website URL exists."""
    if not website_url:
        return False

    normalized = website_url.strip().rstrip("/").lower()
    if not normalized:
        return False

    existing_urls = db_session.execute(
        select(Company.website).where(Company.website.is_not(None))
    ).scalars().all()

    for existing in existing_urls:
        if str(existing).strip().rstrip("/").lower() == normalized:
            return True

    return False


def save_to_database(company_dict: dict[str, Any], db_session: Session) -> str:
    """Insert a cleaned company record and return the new UUID."""
    industry = company_dict.get("industry") or classify_industry(company_dict.get("category"))
    state = normalize_state(company_dict.get("state"))

    try:
        company = Company(
            id=uuid.uuid4(),
            name=company_dict.get("name"),
            website=company_dict.get("website"),
            industry=industry,
            city=company_dict.get("city"),
            state=state,
            source=company_dict.get("source"),
            source_url=company_dict.get("source_url"),
        )
        db_session.add(company)
        db_session.flush()
        db_session.commit()
        return str(company.id)
    except Exception:
        db_session.rollback()
        raise


def normalize_state(raw_state: Optional[str]) -> Optional[str]:
    """Normalize a raw state value to a two-letter uppercase code."""
    if not raw_state:
        return None

    normalized = re.sub(r"\s+", " ", raw_state.strip().lower())
    return _STATE_MAP.get(normalized)


def clean_phone(raw_phone: Optional[str]) -> Optional[str]:
    """Normalize a raw phone string to (716) 555-1234 format."""
    if not raw_phone:
        return None

    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        return None

    area_code, exchange, subscriber = digits[:3], digits[3:6], digits[6:]
    return f"({area_code}) {exchange}-{subscriber}"


def _extract_name(soup: BeautifulSoup, raw_text: str) -> Optional[str]:
    meta_name = soup.find("meta", property="og:site_name") or soup.find("meta", attrs={"name": "title"})
    if meta_name:
        content = _get_attribute_string(meta_name, "content")
        if content:
            return content.strip()

    for tag_name in ("h1", "h2", "title"):
        tag = soup.find(tag_name)
        if tag:
            text_value = tag.get_text(" ", strip=True)
            if text_value:
                return text_value

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return lines[0] if lines else None


def _extract_website(soup: BeautifulSoup, raw_text: str) -> Optional[str]:
    for anchor in soup.find_all("a", href=True):
        anchor_text = anchor.get_text(" ", strip=True)
        if re.search(r"website|visit|learn more", anchor_text, re.IGNORECASE):
            href = _get_attribute_string(anchor, "href")
            if href:
                return href.strip()

    for anchor in soup.find_all("a", href=True):
        href = _get_attribute_string(anchor, "href")
        if href and href.lower().startswith(("http://", "https://")):
            return href.strip()

    match = _URL_REGEX.search(raw_text)
    return match.group(0) if match else None


def _extract_category(soup: BeautifulSoup, raw_text: str) -> Optional[str]:
    candidate = _find_text_by_attr(soup, ("category", "industry", "sector", "classification"))
    if candidate:
        return _strip_label(candidate)

    label_match = re.search(
        r"(?:category|industry|sector)\s*:?\s*(?P<value>[A-Za-z &/,-]+)",
        raw_text,
        re.IGNORECASE,
    )
    return label_match.group("value").strip() if label_match else None


def _extract_phone(soup: BeautifulSoup, raw_text: str) -> Optional[str]:
    phone_link = soup.find("a", href=re.compile(r"^tel:", re.IGNORECASE))
    if phone_link:
        href = _get_attribute_string(phone_link, "href")
        if href:
            return clean_phone(href.split(":", 1)[1])

    phone_text = _find_text_by_attr(soup, ("phone", "telephone", "tel"))
    if phone_text:
        cleaned = clean_phone(phone_text)
        if cleaned:
            return cleaned

    match = _PHONE_REGEX.search(raw_text)
    return clean_phone(match.group(0)) if match else None


def _extract_city_state(soup: BeautifulSoup, raw_text: str) -> tuple[Optional[str], Optional[str]]:
    city_value = _find_text_by_attr(soup, ("city", "locality"))
    state_value = _find_text_by_attr(soup, ("state", "region", "province"))

    city = _strip_label(city_value) if city_value else None
    state = normalize_state(_strip_label(state_value)) if state_value else None

    if city and state:
        return city, state

    address_value = _find_text_by_attr(soup, ("address", "location"))
    location_text = address_value or raw_text
    match = _CITY_STATE_REGEX.search(location_text)
    if match:
        return match.group("city").strip(), normalize_state(match.group("state"))

    return city, state


def _find_text_by_attr(soup: BeautifulSoup, keywords: tuple[str, ...]) -> Optional[str]:
    pattern = re.compile("|".join(re.escape(keyword) for keyword in keywords), re.IGNORECASE)
    for tag in soup.find_all(True):
        classes = _get_attribute_string(tag, "class") or ""
        tag_id = _get_attribute_string(tag, "id") or ""
        if pattern.search(classes) or pattern.search(tag_id):
            text_value = tag.get_text(" ", strip=True)
            if text_value:
                return text_value
    return None


def _strip_label(value: str) -> str:
    return re.sub(r"^(category|industry|sector|city|state|phone|telephone|location|address)\s*:?\s*", "", value, flags=re.IGNORECASE).strip()


def _get_attribute_string(tag: Any, attribute_name: str) -> Optional[str]:
    value = tag.get(attribute_name)
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)