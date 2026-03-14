"""
Scraper for LinkedIn Jobs via public (unauthenticated) HTML endpoint.

LinkedIn's public job search page is accessible without authentication.
We use the /jobs/search/ endpoint which returns JSON-LD structured data.

Note: LinkedIn may rate-limit or block scraping. This is for research/personal use.
"""
import logging
import json
import re
from typing import List, Dict
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup

from config import SEARCH_KEYWORDS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://www.linkedin.com"

SEARCH_PARAMS_LIST = [
    # Ukraine
    {
        "keywords": "CIO \"Chief Information Officer\" \"Head of IT\" \"IT Director\"",
        "location": "Ukraine",
        "f_TPR": "r604800",
        "position": "1",
        "pageNum": "0",
    },
    # Europe (remote)
    {
        "keywords": "CIO \"Head of IT\" \"IT Manager\" \"VP of Technology\"",
        "location": "Europe",
        "f_WT": "2",          # Remote
        "f_TPR": "r604800",
        "position": "1",
        "pageNum": "0",
    },
    # Europe (on-site / hybrid)
    {
        "keywords": "\"IT Director\" \"Director of Technology\" \"Head of Digital Transformation\"",
        "location": "Europe",
        "f_TPR": "r604800",
        "position": "1",
        "pageNum": "0",
    },
    # Cyprus
    {
        "keywords": "CIO \"Chief Information Officer\" \"Head of IT\" \"IT Director\"",
        "location": "Cyprus",
        "f_TPR": "r604800",
        "position": "1",
        "pageNum": "0",
    },
    # Remote worldwide
    {
        "keywords": "\"Head of Automation\" \"IT Operations Manager\" \"Head of Digital Transformation\"",
        "location": "",
        "f_WT": "2",
        "f_TPR": "r604800",
        "position": "1",
        "pageNum": "0",
    },
]

HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SEARCH_KEYWORDS)


def _parse_job_cards(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    results = []

    # LinkedIn public page job cards
    cards = soup.select(
        "div.base-card, li.jobs-search__results-list > div, "
        "div.job-search-card, li[class*='result-card']"
    )

    for card in cards:
        # Title
        title_tag = card.select_one(
            "h3.base-search-card__title, h3[class*='title'], "
            "a[class*='job-card-title'], span[class*='title']"
        )
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)

        # URL
        link_tag = card.select_one("a.base-card__full-link, a[class*='card-title'], a[href*='/jobs/view/']")
        if not link_tag:
            continue
        href = link_tag.get("href", "")
        # Strip query string from LinkedIn URL for dedup
        full_url = href.split("?")[0] if href.startswith("http") else urljoin(base_url, href)

        # Company
        company_tag = card.select_one(
            "h4.base-search-card__subtitle, a[class*='company'], "
            "span[class*='company'], h4[class*='company']"
        )
        company = company_tag.get_text(strip=True) if company_tag else ""

        # Location
        location_tag = card.select_one(
            "span.job-search-card__location, span[class*='location']"
        )
        location = location_tag.get_text(strip=True) if location_tag else ""

        # LinkedIn public cards rarely show salary
        salary = ""

        if not _keyword_match(title):
            continue

        results.append({
            "title": title,
            "company": company,
            "url": full_url,
            "source": "linkedin",
            "salary": salary,
            "location": location,
            "description": f"{title} at {company}. Location: {location}",
        })

    return results


def _parse_json_ld(soup: BeautifulSoup) -> List[Dict]:
    """Try to extract job listings from JSON-LD script tags."""
    results = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("@graph", [data])
            else:
                continue

            for item in items:
                if item.get("@type") not in ("JobPosting", "jobPosting"):
                    continue
                title = item.get("title", "")
                company = ""
                org = item.get("hiringOrganization", {})
                if isinstance(org, dict):
                    company = org.get("name", "")
                location = ""
                loc = item.get("jobLocation", {})
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    if isinstance(addr, dict):
                        location = ", ".join(filter(None, [
                            addr.get("addressLocality", ""),
                            addr.get("addressCountry", ""),
                        ]))
                url = item.get("url", "")
                description = item.get("description", "")[:2000]
                salary = ""
                sal = item.get("baseSalary", {})
                if isinstance(sal, dict):
                    val = sal.get("value", {})
                    if isinstance(val, dict):
                        min_v = val.get("minValue", "")
                        max_v = val.get("maxValue", "")
                        currency = sal.get("currency", "")
                        if min_v or max_v:
                            salary = f"{min_v}–{max_v} {currency}".strip()

                if not url or not _keyword_match(title + " " + description):
                    continue

                results.append({
                    "title": title,
                    "company": company,
                    "url": url.split("?")[0],
                    "source": "linkedin",
                    "salary": salary,
                    "location": location,
                    "description": description,
                })
        except (json.JSONDecodeError, AttributeError):
            continue

    return results


def _scrape_search(client: httpx.Client, params: dict) -> List[Dict]:
    url = f"{BASE_URL}/jobs/search/?" + urlencode(
        {k: v for k, v in params.items() if v}
    )
    results = []

    try:
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("LinkedIn rate-limited (429). Skipping.")
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try JSON-LD first (richer data)
        ld_results = _parse_json_ld(soup)
        if ld_results:
            results.extend(ld_results)
        else:
            # Fall back to HTML card parsing
            results.extend(_parse_job_cards(soup, BASE_URL))

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logger.warning("LinkedIn rate-limited. Skipping.")
        else:
            logger.error("LinkedIn HTTP error: %s", exc)
    except httpx.HTTPError as exc:
        logger.error("LinkedIn connection error: %s", exc)
    except Exception as exc:
        logger.exception("LinkedIn unexpected error: %s", exc)

    return results


def fetch_vacancies() -> List[Dict]:
    """Fetch and filter vacancies from LinkedIn public job search."""
    logger.info("Scraping LinkedIn Jobs (public, no auth)")
    all_results: List[Dict] = []
    seen_urls: set = set()

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        for params in SEARCH_PARAMS_LIST:
            for vacancy in _scrape_search(client, params):
                if vacancy["url"] not in seen_urls:
                    seen_urls.add(vacancy["url"])
                    all_results.append(vacancy)

    logger.info("LinkedIn: found %d unique matching vacancies", len(all_results))
    return all_results
