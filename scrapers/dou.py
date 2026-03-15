"""
Scraper for DOU.ua — combines RSS feed (fresh) + HTML search pages (historical).
RSS: https://jobs.dou.ua/vacancies/feeds/
HTML: https://jobs.dou.ua/vacancies/?search=...  and  ?category=Management
"""
import logging
from typing import List, Dict
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from config import DOU_RSS, SEARCH_KEYWORDS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://jobs.dou.ua"

# HTML search/category pages to scrape in addition to RSS
SEARCH_URLS = [
    f"{BASE_URL}/vacancies/?category=Management&exp=5plus",
    f"{BASE_URL}/vacancies/?search=CIO",
    f"{BASE_URL}/vacancies/?search=Head+of+IT",
    f"{BASE_URL}/vacancies/?search=IT+Director",
    f"{BASE_URL}/vacancies/?search=IT+Manager",
    f"{BASE_URL}/vacancies/?search=Head+of+Digital+Transformation",
]


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SEARCH_KEYWORDS)


def _fetch_rss() -> List[Dict]:
    results = []
    try:
        feed = feedparser.parse(DOU_RSS)
        if feed.bozo and feed.bozo_exception:
            logger.warning("DOU feed parse warning: %s", feed.bozo_exception)

        for entry in feed.entries:
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or ""
            link = getattr(entry, "link", "") or ""

            if not _keyword_match(title + " " + summary):
                continue

            company = getattr(entry, "author", "") or ""
            if not company and " в " in title:
                parts = title.split(" в ", 1)
                title = parts[0].strip()
                company = parts[1].strip()
            elif not company and " at " in title.lower():
                title_parts = title.split(" at ", 1) if " at " in title else title.split(" At ", 1)
                title = title_parts[0].strip()
                company = title_parts[1].strip() if len(title_parts) > 1 else ""

            location = "Україна / Remote"
            if hasattr(entry, "tags"):
                for tag in entry.tags:
                    term = tag.get("term", "")
                    if any(city in term for city in ["Київ", "Львів", "Харків", "Remote"]):
                        location = term
                        break

            results.append({
                "title": title,
                "company": company,
                "url": link,
                "source": "dou",
                "salary": "",
                "location": location,
                "description": summary,
            })
    except Exception as exc:
        logger.exception("Error scraping DOU RSS: %s", exc)

    return results


def _fetch_html_page(client: httpx.Client, url: str) -> List[Dict]:
    results = []
    try:
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        for card in soup.select("li.l-vacancy"):
            # Title and URL
            title_tag = card.select_one("a.vt")
            if not title_tag:
                # fallback: first anchor linking to a vacancy page
                title_tag = card.select_one('a[href*="/vacancies/"]')
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else urljoin(BASE_URL, href)

            # Company: anchor inside .company block or strong tag
            company = ""
            company_tag = card.select_one("a.company")
            if company_tag:
                company = company_tag.get_text(strip=True)
            else:
                strong = card.select_one("strong")
                if strong:
                    company = strong.get_text(strip=True).lstrip("в").strip()

            # Location: span or div with city/remote info
            location = ""
            for loc_tag in card.select("span.cities, span.city, .place"):
                txt = loc_tag.get_text(strip=True)
                if txt:
                    location = txt
                    break
            if not location:
                # fallback: look for "remote" / "віддалено" text in card
                card_text = card.get_text(" ", strip=True)
                for hint in ["віддалено", "remote", "дистанційно"]:
                    if hint in card_text.lower():
                        location = "Remote"
                        break

            # Description snippet
            desc_tag = card.select_one("div.sh-info, p.text")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            if not _keyword_match(title + " " + description):
                continue

            results.append({
                "title": title,
                "company": company,
                "url": full_url,
                "source": "dou",
                "salary": "",
                "location": location or "Україна",
                "description": description,
            })

    except httpx.HTTPError as exc:
        logger.error("DOU HTML error for %s: %s", url, exc)
    except Exception as exc:
        logger.exception("DOU HTML unexpected error for %s: %s", url, exc)

    return results


def fetch_vacancies() -> List[Dict]:
    """Fetch vacancies from DOU.ua via RSS + HTML search pages."""
    logger.info("Scraping DOU RSS: %s", DOU_RSS)
    seen_urls: set = set()
    all_results: List[Dict] = []

    # 1. RSS (most recent)
    for v in _fetch_rss():
        if v["url"] not in seen_urls:
            seen_urls.add(v["url"])
            all_results.append(v)

    # 2. HTML search/category pages (catches older postings)
    with httpx.Client(headers=REQUEST_HEADERS, follow_redirects=True) as client:
        for url in SEARCH_URLS:
            for v in _fetch_html_page(client, url):
                if v["url"] not in seen_urls:
                    seen_urls.add(v["url"])
                    all_results.append(v)

    logger.info("DOU: found %d matching vacancies", len(all_results))
    return all_results
