"""
Scraper for Robota.ua via public JSON API.
https://api.robota.ua/vacancy/search
"""
import logging
from typing import List, Dict

import httpx

from config import SEARCH_KEYWORDS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

API_URL = "https://api.robota.ua/vacancy/search"
VACANCY_URL_WITH_COMPANY = "https://robota.ua/company{notebook_id}/vacancy{id}"
VACANCY_URL_FALLBACK = "https://robota.ua/vacancy{id}"

SEARCH_TERMS = [
    "CIO",
    "Chief Information Officer",
    "Head of IT",
    "IT Manager",
    "IT Director",
    "Director of Technology",
    "VP of Technology",
    "Head of Digital Transformation",
    "Head of Automation",
    "IT Operations Manager",
]


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SEARCH_KEYWORDS)


def _build_salary(doc: dict) -> str:
    salary_from = doc.get("salaryFrom") or 0
    salary_to = doc.get("salaryTo") or 0
    comment = (doc.get("salaryComment") or "").strip()

    if salary_from and salary_to:
        return f"{salary_from}–{salary_to} грн"
    if salary_from:
        return f"від {salary_from} грн"
    if salary_to:
        return f"до {salary_to} грн"
    return comment


def _fetch_term(client: httpx.Client, keywords: str) -> List[Dict]:
    results = []
    try:
        resp = client.get(
            API_URL,
            params={"keywords": keywords, "cityId": 0},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        for doc in data.get("documents", []):
            title = doc.get("name", "").strip()
            description = doc.get("shortDescription", "").strip()

            if not _keyword_match(title + " " + description):
                continue

            vacancy_id = doc.get("id")
            notebook_id = doc.get("notebookId") or 0
            if notebook_id:
                url = VACANCY_URL_WITH_COMPANY.format(notebook_id=notebook_id, id=vacancy_id)
            else:
                url = VACANCY_URL_FALLBACK.format(id=vacancy_id)

            results.append({
                "title": title,
                "company": doc.get("companyName", "").strip(),
                "url": url,
                "source": "Robota.ua",
                "salary": _build_salary(doc),
                "location": doc.get("cityName", "").strip(),
                "description": description,
            })

    except httpx.HTTPError as exc:
        logger.error("Robota.ua HTTP error for '%s': %s", keywords, exc)
    except Exception as exc:
        logger.exception("Robota.ua unexpected error for '%s': %s", keywords, exc)

    return results


def fetch_vacancies() -> List[Dict]:
    """Fetch vacancies from Robota.ua via public API."""
    logger.info("Scraping Robota.ua")
    all_results: List[Dict] = []
    seen_urls: set = set()

    with httpx.Client(headers=REQUEST_HEADERS, follow_redirects=True) as client:
        for term in SEARCH_TERMS:
            for vacancy in _fetch_term(client, term):
                if vacancy["url"] not in seen_urls:
                    seen_urls.add(vacancy["url"])
                    all_results.append(vacancy)

    logger.info("Robota.ua: found %d unique matching vacancies", len(all_results))
    return all_results
