"""
Scraper for Work.ua via server-rendered category pages.
Search pages (/jobs/?q=...) require JS rendering — category URLs work fine.
"""
import logging
from typing import List, Dict
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from config import SEARCH_KEYWORDS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://www.work.ua"

# Category-style URLs that Work.ua renders server-side
SEARCH_SLUGS = [
    "cio",
    "chief+information+officer",
    "head+of+it",
    "it+manager",
    "it+director",
    "director+of+technology",
    "vp+of+technology",
    "head+of+digital+transformation",
    "head+of+automation",
    "it+operations+manager",
]


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SEARCH_KEYWORDS)


def _format_salary(tag) -> str:
    if not tag:
        return ""
    return " ".join(tag.get_text(separator=" ", strip=True).split())


def _scrape_slug(client: httpx.Client, slug: str) -> List[Dict]:
    url = f"{BASE_URL}/jobs-{slug}/"
    results = []

    try:
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        cards = soup.select("div.job-link")
        for card in cards:
            title_tag = card.select_one("h2 a, h3 a")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            if not href:
                continue
            full_url = urljoin(BASE_URL, href)

            # Company: span.mr-xs holds company name
            company_tag = card.select_one("span.mr-xs")
            company = company_tag.get_text(strip=True) if company_tag else ""

            # Salary: first span.strong-600 typically contains salary
            salary_tag = card.select_one("span.strong-600")
            salary = _format_salary(salary_tag) if salary_tag else ""

            # Location: plain <span> sibling after company block
            location = ""
            for span in card.select("span"):
                cls = " ".join(span.get("class") or [])
                txt = span.get_text(strip=True)
                if not cls and txt and len(txt) < 40 and txt not in (title, company, salary):
                    location = txt
                    break

            # Description snippet
            desc_tag = card.select_one("p.ellipsis")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            if not _keyword_match(title + " " + description):
                continue

            results.append({
                "title": title,
                "company": company,
                "url": full_url,
                "source": "Work.ua",
                "salary": salary,
                "location": location,
                "description": description,
            })

    except httpx.HTTPError as exc:
        logger.error("Work.ua HTTP error for slug '%s': %s", slug, exc)
    except Exception as exc:
        logger.exception("Work.ua unexpected error for slug '%s': %s", slug, exc)

    return results


def fetch_vacancies() -> List[Dict]:
    """Fetch vacancies from Work.ua using server-rendered category pages."""
    logger.info("Scraping Work.ua")
    all_results: List[Dict] = []
    seen_urls: set = set()

    with httpx.Client(headers=REQUEST_HEADERS, follow_redirects=True) as client:
        for slug in SEARCH_SLUGS:
            for vacancy in _scrape_slug(client, slug):
                if vacancy["url"] not in seen_urls:
                    seen_urls.add(vacancy["url"])
                    all_results.append(vacancy)

    logger.info("Work.ua: found %d unique matching vacancies", len(all_results))
    return all_results
