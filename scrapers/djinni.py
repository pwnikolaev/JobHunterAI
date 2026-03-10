"""
Scraper for Djinni.co via public JSON API.
https://djinni.co/api/jobs/
"""
import logging
from typing import List, Dict

import httpx

from config import SEARCH_KEYWORDS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

API_URL = "https://djinni.co/api/jobs/"
VACANCY_URL = "https://djinni.co/jobs/{slug}/"

# Djinni is a Ukrainian/remote-focused board — all results are relevant geographically.
# We fetch all and filter by keyword.
PAGE_LIMIT = 50


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SEARCH_KEYWORDS)


def _build_salary(job: dict) -> str:
    min_s = job.get("public_salary_min") or 0
    max_s = job.get("public_salary_max") or 0
    if min_s and max_s:
        return f"${min_s}–${max_s}"
    if min_s:
        return f"від ${min_s}"
    if max_s:
        return f"до ${max_s}"
    return ""


def fetch_vacancies() -> List[Dict]:
    """Fetch matching vacancies from Djinni public API."""
    logger.info("Scraping Djinni API")
    results: List[Dict] = []
    seen_ids: set = set()

    with httpx.Client(headers=REQUEST_HEADERS, follow_redirects=True) as client:
        offset = 0
        while True:
            try:
                resp = client.get(
                    API_URL,
                    params={"limit": PAGE_LIMIT, "offset": offset},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("Djinni API error at offset %d: %s", offset, exc)
                break

            jobs = data.get("results", [])
            if not jobs:
                break

            for job in jobs:
                job_id = job.get("id")
                if job_id in seen_ids:
                    continue

                title = job.get("title", "").strip()
                description = job.get("long_description", "").strip()

                if not _keyword_match(title + " " + description):
                    continue

                seen_ids.add(job_id)
                slug = job.get("slug", str(job_id))
                location = job.get("location", "").strip() or "Remote / Ukraine"

                results.append({
                    "title": title,
                    "company": job.get("company_name", "").strip(),
                    "url": VACANCY_URL.format(slug=slug),
                    "source": "Djinni",
                    "salary": _build_salary(job),
                    "location": location,
                    "description": description[:3000],
                })

            # Stop if we've scanned all pages or found enough
            total = data.get("count", 0)
            offset += PAGE_LIMIT
            if offset >= total or offset > 500:  # cap at 500 to avoid hammering
                break

    logger.info("Djinni: found %d matching vacancies", len(results))
    return results
