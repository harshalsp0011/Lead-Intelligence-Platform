from __future__ import annotations

"""Website crawling helpers for the Scout agent.

This module visits company websites (including JavaScript-rendered pages) to
collect extra signals used for enrichment and scoring.
"""

import re
from importlib import import_module
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_LOCATION_KEYWORDS = (
    "locations",
    "our locations",
    "find a",
    "stores",
    "hospitals",
    "properties",
    "facilities",
    "branches",
)

_LOCATION_PATTERNS = (
    r"\b([0-9]{1,3}(?:,[0-9]{3})*)\s+(locations|hospitals|stores|facilities|properties|sites)\b",
    r"\b(over|more than)\s+([0-9]{1,3}(?:,[0-9]{3})*)\s+(locations|hospitals|stores|facilities|properties|sites)\b",
)

_EMPLOYEE_PATTERNS = (
    r"\b([0-9]{1,3}(?:,[0-9]{3})*)\s+employees\b",
    r"\bteam\s+of\s+([0-9]{1,3}(?:,[0-9]{3})*)\b",
    r"\b([0-9]{1,3}(?:,[0-9]{3})*)\s+staff\b",
    r"\b([0-9]{1,3}(?:,[0-9]{3})*)\s+professionals\b",
    r"\bover\s+([0-9]{1,3}(?:,[0-9]{3})*)\s+people\b",
)


def crawl_company_site(website_url: str) -> dict[str, object]:
    """Visit a company website and return raw content plus extracted signals."""
    normalized_url = _normalize_url(website_url)

    if not normalized_url:
        return {
            "raw_text": "",
            "raw_html": "",
            "location_count": 1,
            "employee_signal": 0,
            "facility_type": "unknown",
            "has_locations_page": False,
        }

    try:
        sync_api = import_module("playwright.sync_api")
        _use_playwright = True
    except ModuleNotFoundError:
        _use_playwright = False

    homepage_html = ""
    homepage_text = ""
    locations_html = ""
    locations_text = ""
    locations_url: Optional[str] = None

    if _use_playwright:
        sync_playwright = sync_api.sync_playwright  # type: ignore[possibly-undefined]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(normalized_url, wait_until="domcontentloaded", timeout=15000)
                homepage_html = page.content()
                homepage_text = page.inner_text("body")

                locations_url = find_locations_page(normalized_url, homepage_html)
                if locations_url:
                    page.goto(locations_url, wait_until="domcontentloaded", timeout=15000)
                    locations_html = page.content()
                    locations_text = page.inner_text("body")
            finally:
                browser.close()
    else:
        # Fallback: plain HTTP fetch with BeautifulSoup
        _headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadBot/1.0)"}
        try:
            resp = requests.get(normalized_url, headers=_headers, timeout=10)
            homepage_html = resp.text
            soup = BeautifulSoup(homepage_html, "html.parser")
            homepage_text = soup.get_text(" ", strip=True)
            locations_url = find_locations_page(normalized_url, homepage_html)
            if locations_url:
                resp2 = requests.get(locations_url, headers=_headers, timeout=10)
                locations_html = resp2.text
                locations_text = BeautifulSoup(locations_html, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass

    text_for_counts = locations_text or homepage_text
    url_for_counts = locations_url or normalized_url
    combined_text = "\n".join([chunk for chunk in (homepage_text, locations_text) if chunk]).strip()

    location_count = extract_location_count(text_for_counts, url_for_counts)
    employee_signal = extract_employee_signals(combined_text or text_for_counts)
    facility_type = detect_facility_type(combined_text or text_for_counts, "unknown")

    return {
        "raw_text": combined_text or homepage_text,
        "raw_html": locations_html or homepage_html,
        "location_count": location_count,
        "employee_signal": employee_signal,
        "facility_type": facility_type,
        "has_locations_page": locations_url is not None,
    }


def find_locations_page(homepage_url: str, page_html: str) -> Optional[str]:
    """Find the first likely locations page URL from homepage HTML."""
    soup = BeautifulSoup(page_html or "", "html.parser")

    for anchor in soup.find_all("a", href=True):
        href = _get_attribute_string(anchor, "href")
        if not href:
            continue

        text_value = (anchor.get_text(" ", strip=True) or "").lower()
        title_value = (_get_attribute_string(anchor, "title") or "").lower()
        aria_value = (_get_attribute_string(anchor, "aria-label") or "").lower()
        href_value = href.lower()

        if any(keyword in text_value or keyword in title_value or keyword in aria_value or keyword in href_value for keyword in _LOCATION_KEYWORDS):
            return urljoin(homepage_url, href)

    return None


def extract_location_count(page_text: str, page_url: str) -> int:
    """Estimate company location count from page text patterns."""
    haystack = f"{page_text}\n{page_url}".lower()

    for pattern in _LOCATION_PATTERNS:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match:
            for group in match.groups():
                parsed = _parse_int(group)
                if parsed is not None:
                    return parsed

    return 1


def extract_employee_signals(page_text: str) -> int:
    """Estimate employee count from text patterns."""
    haystack = (page_text or "").lower()

    for pattern in _EMPLOYEE_PATTERNS:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if not match:
            continue

        for group in match.groups():
            parsed = _parse_int(group)
            if parsed is not None:
                return parsed

    return 0


def detect_facility_type(page_text: str, industry: str) -> str:
    """Infer a primary facility type from website text and industry."""
    text_value = (page_text or "").lower()
    industry_value = (industry or "unknown").lower()

    if industry_value == "healthcare" and "hospital" in text_value:
        return "hospital"

    if industry_value == "manufacturing" and ("plant" in text_value or "factory" in text_value):
        return "plant"

    if "warehouse" in text_value:
        return "warehouse"
    if "hotel" in text_value or "resort" in text_value:
        return "hotel"
    if "store" in text_value or "shop" in text_value:
        return "store"
    if "office" in text_value or "headquarters" in text_value:
        return "office"

    return industry_value or "unknown"


def is_site_reachable(url: str) -> bool:
    """Return True when a URL responds with an HTTP status code under 400."""
    normalized_url = _normalize_url(url)
    if not normalized_url:
        return False

    try:
        response = requests.head(normalized_url, timeout=5, allow_redirects=True)
        return response.status_code < 400
    except Exception:
        return False


def _normalize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    candidate = url.strip()
    if not candidate:
        return None

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if not parsed.netloc:
        return None

    return candidate


def _parse_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None

    digits = re.sub(r"[^0-9]", "", value)
    if not digits:
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def _get_attribute_string(tag: object, attribute_name: str) -> Optional[str]:
    get_attr = getattr(tag, "get", None)
    if not callable(get_attr):
        return None

    value = get_attr(attribute_name)
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)
