from __future__ import annotations

"""Directory scraping helpers for the Scout agent.

This file loads active directory sources, fetches directory pages, follows
pagination, and extracts raw company listing cards. It is meant to work with
the company extractor, which cleans these raw listings before saving them.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from config.settings import get_settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DIRECTORY_SOURCES_PATH = _PROJECT_ROOT / "data" / "sources" / "directory_urls.json"
_LISTING_HINTS = ("listing", "result", "member", "business", "company", "card")


def scrape_directory(directory_url: str, proxy_url: Optional[str] = None) -> list[dict[str, Optional[str]]]:
    """Scrape all company listings from a directory, following pagination."""
    found_companies: list[dict[str, Optional[str]]] = []
    visited_urls: set[str] = set()
    current_url: Optional[str] = directory_url

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)
        page_html = fetch_page(current_url, proxy_url=proxy_url)
        soup = BeautifulSoup(page_html, "html.parser")

        for listing in _find_listing_elements(soup):
            parsed_listing = parse_listing(listing)
            if parsed_listing is not None:
                found_companies.append(parsed_listing)

        current_url = get_next_page(current_url, page_html)

    return found_companies


def parse_listing(listing_html_element: Tag) -> Optional[dict[str, Optional[str]]]:
    """Extract core company fields from a single listing element."""
    soup = listing_html_element if isinstance(listing_html_element, Tag) else BeautifulSoup(str(listing_html_element), "html.parser")

    name = _extract_name_from_listing(soup)
    if not name:
        return None

    website = _extract_website_from_listing(soup)
    category = _extract_text_by_keywords(soup, ("category", "industry", "sector", "business"))
    city = _extract_text_by_keywords(soup, ("city", "location", "address", "locality"))

    if city:
        city = _clean_labeled_text(city)

    if category:
        category = _clean_labeled_text(category)

    return {
        "name": name,
        "website": website,
        "category": category,
        "city": city,
        "raw_html": str(soup),
    }


def get_next_page(current_url: str, page_html: str) -> Optional[str]:
    """Return the next pagination URL from a directory page, if one exists."""
    soup = BeautifulSoup(page_html, "html.parser")

    for anchor in soup.find_all("a", href=True):
        rel_value = (_get_attribute_string(anchor, "rel") or "").lower()
        href = _get_attribute_string(anchor, "href")
        if "next" in rel_value and href:
            return urljoin(current_url, href)

    for anchor in soup.find_all("a", href=True):
        link_text = anchor.get_text(" ", strip=True).lower()
        aria_label = (_get_attribute_string(anchor, "aria-label") or "").lower()
        classes = (_get_attribute_string(anchor, "class") or "").lower()
        href = _get_attribute_string(anchor, "href")
        if any(token in (link_text, aria_label) for token in ("next", ">", "›", "→")) and href:
            return urljoin(current_url, href)
        if ("next" in classes or "next" in aria_label) and href:
            return urljoin(current_url, href)

    parsed_current = urlparse(current_url)
    current_page_number = _extract_page_number(parsed_current.path) or _extract_page_number(parsed_current.query)
    if current_page_number is None:
        return None

    for anchor in soup.find_all("a", href=True):
        page_number = _extract_page_number(anchor.get_text(" ", strip=True))
        href = _get_attribute_string(anchor, "href")
        if page_number == current_page_number + 1 and href:
            return urljoin(current_url, href)

    return None


def respect_rate_limit(delay_seconds: float) -> None:
    """Sleep before the next request, falling back to configured delay."""
    settings = get_settings()
    actual_delay = delay_seconds or settings.REQUEST_DELAY_SECONDS
    time.sleep(actual_delay)


def fetch_page(url: str, proxy_url: Optional[str] = None) -> str:
    """Fetch a page with realistic headers and retry on transient failures."""
    settings = get_settings()
    headers = {
        "User-Agent": str(settings.SCRAPER_USER_AGENT),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
    }
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    last_error: Exception | None = None
    for attempt in range(settings.MAX_RETRIES):
        try:
            response = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=settings.SCRAPER_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "Directory fetch failed for %s on attempt %s/%s: %s",
                url,
                attempt + 1,
                settings.MAX_RETRIES,
                exc,
            )
            if attempt == settings.MAX_RETRIES - 1:
                break
        finally:
            respect_rate_limit(settings.REQUEST_DELAY_SECONDS)

    logger.error("Failed to fetch %s after %s attempts", url, settings.MAX_RETRIES)
    raise RuntimeError(f"Failed to fetch {url} after {settings.MAX_RETRIES} attempts") from last_error


def load_directory_sources() -> list[dict[str, Any]]:
    """Load active directory source definitions from JSON."""
    sources = json.loads(_DIRECTORY_SOURCES_PATH.read_text(encoding="utf-8"))
    return [source for source in sources if source.get("active") is True]


def _find_listing_elements(soup: BeautifulSoup) -> list[Tag]:
    """Return HTML elements that look like company listing cards."""
    candidates: list[Tag] = []
    seen: set[int] = set()

    for tag in soup.find_all(["article", "div", "li", "section"]):
        classes = (_get_attribute_string(tag, "class") or "").lower()
        tag_id = (_get_attribute_string(tag, "id") or "").lower()
        if any(hint in classes or hint in tag_id for hint in _LISTING_HINTS):
            tag_identity = id(tag)
            if tag_identity not in seen:
                candidates.append(tag)
                seen.add(tag_identity)

    if candidates:
        return candidates

    for anchor in soup.find_all("a", href=True):
        parent = anchor.find_parent(["article", "div", "li", "section"])
        if parent is not None and len(parent.get_text(" ", strip=True)) > 20:
            tag_identity = id(parent)
            if tag_identity not in seen:
                candidates.append(parent)
                seen.add(tag_identity)

    return candidates


def _extract_name_from_listing(tag: Tag) -> Optional[str]:
    """Extract the company name from one listing card."""
    for selector in ("h1", "h2", "h3", "h4", "[itemprop='name']", "a[title]"):
        element = tag.select_one(selector)
        if element:
            text_value = element.get_text(" ", strip=True) or _get_attribute_string(element, "title")
            if text_value:
                return text_value.strip()

    first_link = tag.find("a", href=True)
    if first_link:
        text_value = first_link.get_text(" ", strip=True)
        if text_value:
            return text_value

    text_lines = [line.strip() for line in tag.get_text("\n", strip=True).splitlines() if line.strip()]
    return text_lines[0] if text_lines else None


def _extract_website_from_listing(tag: Tag) -> Optional[str]:
    """Extract the first absolute website URL found inside a listing card."""
    for anchor in tag.find_all("a", href=True):
        href = _get_attribute_string(anchor, "href")
        if href and href.strip().lower().startswith(("http://", "https://")):
            return href.strip()
    return None


def _extract_text_by_keywords(tag: Tag, keywords: tuple[str, ...]) -> Optional[str]:
    """Find text content in a listing card using class, id, or regex keyword hints."""
    for element in tag.find_all(True):
        classes = (_get_attribute_string(element, "class") or "").lower()
        tag_id = (_get_attribute_string(element, "id") or "").lower()
        if any(keyword in classes or keyword in tag_id for keyword in keywords):
            text_value = element.get_text(" ", strip=True)
            if text_value:
                return text_value

    text_value = tag.get_text(" ", strip=True)
    if any(re.search(keyword, text_value, re.IGNORECASE) for keyword in keywords):
        return text_value

    return None


def _clean_labeled_text(value: str) -> str:
    """Strip any leading field label such as `City:` from extracted text."""
    return value.split(":", 1)[1].strip() if ":" in value else value.strip()


def _extract_page_number(value: str) -> Optional[int]:
    """Extract a page number from pagination text or URLs."""
    match = re.search(r"\bpage(?:=|/)?\s*(\d+)\b|\b(\d+)\b", value, re.IGNORECASE)
    if not match:
        return None

    page_number = match.group(1) or match.group(2)
    return int(page_number) if page_number else None


def _get_attribute_string(tag: Any, attribute_name: str) -> Optional[str]:
    """Return a tag attribute as a normalized string."""
    value = tag.get(attribute_name)
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)