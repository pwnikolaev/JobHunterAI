"""
Scraper for Robota.ua candidate resumes via public search page (HTML).

The JSON API at api.robota.ua/resume/search requires employer authentication.
This scraper instead uses the public website search with keyword slugs.
"""
import logging
from typing import List, Dict
from urllib.parse import urljoin, quote

import httpx
from bs4 import BeautifulSoup

from config import REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://robota.ua"

# Search URLs for robota.ua public resume search
SEARCH_SLUGS = [
    "керівник-відділу-продажів",
    "начальник-відділу-продажів",
    "head-of-sales",
]

TITLE_KEYWORDS = [
    "продаж",
    "sales",
    "збут",
    "комерційний",
    "керівник відділу",
    "начальник відділу",
    "head of sales",
    "директор продажів",
    "директор з продажу",
]


def _title_matches(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in TITLE_KEYWORDS)


def _parse_page(soup: BeautifulSoup) -> List[Dict]:
    """Parse resume cards from Robota.ua search results page."""
    results = []

    # Robota.ua SPA — try common selectors for pre-rendered content
    cards = (
        soup.select("app-resume-card")
        or soup.select("div.cv-card")
        or soup.select("article.resume-card")
        or soup.select("div[class*='resume']")
    )

    for card in cards:
        # Try to find position title link
        title_tag = (
            card.select_one("a.resume-card__title")
            or card.select_one("h2 a")
            or card.select_one("a[href*='/candidate/']")
            or card.select_one("a[href*='/cv/']")
        )
        if not title_tag:
            continue

        position = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        if not href:
            continue

        if not _title_matches(position):
            continue

        full_url = urljoin(BASE_URL, href)
        name = "Анонім"
        location = ""
        salary = ""
        experience = ""
        description = ""

        # Name
        for sel in (".name", "span.candidate-name", "p.name"):
            tag = card.select_one(sel)
            if tag:
                name = tag.get_text(strip=True)
                break

        # Location
        for sel in (".location", "span.city", "[class*='location']"):
            tag = card.select_one(sel)
            if tag:
                location = tag.get_text(strip=True)
                break

        # Salary
        for tag in card.select("span, div"):
            txt = tag.get_text(strip=True)
            if "грн" in txt or "$" in txt:
                salary = txt
                break

        # Description
        for sel in (".description", "p.cut", "div.summary"):
            tag = card.select_one(sel)
            if tag:
                description = tag.get_text(strip=True)
                break

        results.append({
            "name": name,
            "position": position,
            "url": full_url,
            "source": "Robota.ua",
            "location": location,
            "salary": salary,
            "experience": experience,
            "description": description,
        })

    return results


def _fetch_slug(client: httpx.Client, slug: str) -> List[Dict]:
    url = f"{BASE_URL}/candidates/{slug}/"
    results = []

    try:
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (404, 301, 302):
            # Try alternative URL pattern
            url = f"{BASE_URL}/candidates/?q={quote(slug.replace('-', ' '))}"
            resp = client.get(url, timeout=REQUEST_TIMEOUT)

        if resp.status_code not in (200,):
            logger.warning("Robota.ua candidates slug '%s' returned %s", slug, resp.status_code)
            return []

        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        results = _parse_page(soup)

    except httpx.HTTPError as exc:
        logger.error("Robota.ua candidates HTTP error for '%s': %s", slug, exc)
    except Exception as exc:
        logger.exception("Robota.ua candidates unexpected error for '%s': %s", slug, exc)

    if not results:
        logger.info("Robota.ua: no results for slug '%s' (SPA page — requires auth or JS rendering)", slug)

    return results


def fetch_candidates() -> List[Dict]:
    """Fetch candidates from Robota.ua public resume search."""
    logger.info("Scraping Robota.ua resumes")
    all_results: List[Dict] = []
    seen_urls: set = set()

    with httpx.Client(headers=REQUEST_HEADERS, follow_redirects=True) as client:
        for slug in SEARCH_SLUGS:
            for candidate in _fetch_slug(client, slug):
                if candidate["url"] not in seen_urls:
                    seen_urls.add(candidate["url"])
                    all_results.append(candidate)

    logger.info("Robota.ua resumes: found %d candidates", len(all_results))
    return all_results
