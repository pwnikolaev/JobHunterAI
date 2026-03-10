"""
Scraper for DOU.ua via RSS feed.
URL: https://jobs.dou.ua/vacancies/feeds/
"""
import logging
from typing import List, Dict

import feedparser

from config import DOU_RSS, SEARCH_KEYWORDS

logger = logging.getLogger(__name__)


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SEARCH_KEYWORDS)


def fetch_vacancies() -> List[Dict]:
    """Fetch and filter vacancies from DOU.ua RSS."""
    logger.info("Scraping DOU RSS: %s", DOU_RSS)
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

            # DOU entries sometimes have author (company) in tags
            company = getattr(entry, "author", "") or ""

            # Try to get company from title: "Job Title в Company"
            if not company and " в " in title:
                parts = title.split(" в ", 1)
                title = parts[0].strip()
                company = parts[1].strip()
            elif not company and " at " in title.lower():
                parts = title.lower().split(" at ", 1)
                title_parts = title.split(" at ", 1) if " at " in title else title.split(" At ", 1)
                title = title_parts[0].strip()
                company = title_parts[1].strip() if len(title_parts) > 1 else ""

            # Location from tags
            location = "Україна / Remote"
            if hasattr(entry, "tags"):
                for tag in entry.tags:
                    term = tag.get("term", "")
                    if any(city in term for city in ["Київ", "Львів", "Харків", "Remote", "Remote"]):
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

        logger.info("DOU: found %d matching vacancies", len(results))

    except Exception as exc:
        logger.exception("Error scraping DOU: %s", exc)

    return results
