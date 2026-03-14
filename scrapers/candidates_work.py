"""
Scraper for Work.ua candidate resumes via public category pages.

Work.ua ignores keyword search without employer authentication, returning
the most recently updated resumes in each category. We compensate by:
  1. Using management/sales categories (2, 11)
  2. Client-side keyword filtering on position title + desired positions
  3. Walking multiple pages per category

HTML structure of a resume card (from live inspection):

  <div class="card card-hover card-search resume-link ...">
    <h2><a href="/resumes/ID/">Position Title</a></h2>
    <p class="mt-xs mb-0">
      <span class="text-muted">Розглядає посади:</span>
      Desired Position 1, Desired Position 2, ...
    </p>
    <p class="mt-xs mb-0">
      <span class="strong-600">Ім'я</span>,
      <span>22 роки</span>,
      <span> Місто</span>
    </p>
    <p class="mb-0 mt-xs text-muted">Вища освіта · Повна зайнятість</p>
    <ul class="mt-lg mb-0">
      <li>Посада в компанії, <span class="text-muted">Компанія, 3 місяці</span></li>
    </ul>
  </div>
"""
import logging
import time
import random
from typing import List, Dict
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from config import REQUEST_HEADERS, REQUEST_TIMEOUT

# Delay between page requests to avoid 403 rate-limiting
PAGE_DELAY_MIN = 1.5   # seconds
PAGE_DELAY_MAX = 3.0

logger = logging.getLogger(__name__)

BASE_URL = "https://www.work.ua"

# Category IDs on work.ua (public, no-auth)
# 2  = Управління, адміністрування (89K candidates — scan partial)
# 11 = Топ-менеджмент, комерційні директори (2.3K — scan ALL)
CATEGORY_CONFIGS = [
    {"id": 2,  "max_pages": 30},   # 420 candidates
    {"id": 11, "max_pages": 200},  # ~163 pages = all 2279 candidates
]

# Candidate must be in a MANAGEMENT role AND in SALES context
# (to exclude plain "Менеджер з продажу" salespeople)
MANAGEMENT_KEYWORDS = [
    "керівник",
    "начальник",
    "директор",
    "head of",
    "завідувач",
    "вп продаж",
    "vp sales",
    "chief",
]
SALES_KEYWORDS = [
    "продаж",   # продажів, продажу, продажі
    "sales",
    "збут",
    "комерційний",
]


def _text_matches(text: str) -> bool:
    """True if text indicates a SALES MANAGEMENT role (not a plain sales rep)."""
    t = text.lower()
    has_mgmt = any(kw in t for kw in MANAGEMENT_KEYWORDS)
    has_sales = any(kw in t for kw in SALES_KEYWORDS)
    return has_mgmt and has_sales


def _parse_cards(soup: BeautifulSoup) -> List[Dict]:
    results = []
    cards = soup.select("div.resume-link")

    for card in cards:
        # ── Title ──────────────────────────────────────────────────────────
        title_tag = card.select_one("h2 a[href*='/resumes/']")
        if not title_tag:
            continue

        position = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        if not href:
            continue
        full_url = urljoin(BASE_URL, href)

        # ── Desired positions (2nd paragraph, starts with "Розглядає посади:") ──
        desired_positions = ""
        for p in card.select("p.mt-xs"):
            if p.select_one("span.text-muted"):
                # Get text after the label span
                label = p.select_one("span.text-muted")
                raw = p.get_text(separator=" ", strip=True)
                label_txt = label.get_text(strip=True)
                desired_positions = raw.replace(label_txt, "").strip(" ,")
                break

        # ── Client-side relevance filter ───────────────────────────────────
        if not _text_matches(position) and not _text_matches(desired_positions):
            continue

        # ── Name / Age / Location ──────────────────────────────────────────
        # Find the <p> that has span.strong-600 (name)
        name = "Анонім"
        age = ""
        location = ""
        for p in card.select("p.mt-xs"):
            name_span = p.select_one("span.strong-600")
            if name_span:
                name = name_span.get_text(strip=True)
                spans = [s for s in p.select("span") if "strong-600" not in (s.get("class") or [])]
                if len(spans) >= 1:
                    age = spans[0].get_text(strip=True)
                if len(spans) >= 2:
                    location = spans[1].get_text(strip=True).strip(" ,")
                break

        # ── Work experience (list items) ───────────────────────────────────
        exp_parts = []
        for li in card.select("ul.mt-lg li"):
            li_text = li.get_text(separator=" ", strip=True)
            if li_text:
                exp_parts.append(li_text)
        experience = " | ".join(exp_parts[:3]) if exp_parts else age

        # ── Education / format note ────────────────────────────────────────
        edu_tag = card.select_one("p.mb-0.mt-xs.text-muted")
        edu = edu_tag.get_text(strip=True) if edu_tag else ""

        # ── Description: desired positions + education ─────────────────────
        desc_parts = []
        if desired_positions:
            desc_parts.append(f"Розглядає посади: {desired_positions}")
        if exp_parts:
            desc_parts.append("Досвід: " + "; ".join(exp_parts[:3]))
        if edu:
            desc_parts.append(edu)
        description = " | ".join(desc_parts)

        results.append({
            "name": name,
            "position": position,
            "url": full_url,
            "source": "Work.ua",
            "location": location,
            "salary": "",           # Not shown in public listings
            "experience": experience,
            "description": description,
        })

    return results


def _scrape_category(client: httpx.Client, category_id: int, max_pages: int) -> List[Dict]:
    results = []

    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/resumes/?category={category_id}&page={page}"
        try:
            resp = client.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            cards = soup.select("div.resume-link")
            if not cards:
                break  # No more pages

            page_results = _parse_cards(soup)
            results.extend(page_results)

            time.sleep(random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX))

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning("Work.ua category=%d page=%d: 403 rate-limit, waiting 30s", category_id, page)
                time.sleep(30)
                continue
            logger.error("Work.ua category=%d page=%d error: %s", category_id, page, exc)
            break
        except httpx.HTTPError as exc:
            logger.error("Work.ua category=%d page=%d error: %s", category_id, page, exc)
            break
        except Exception as exc:
            logger.exception("Work.ua category=%d page=%d unexpected: %s", category_id, page, exc)
            break

    logger.info("Work.ua category=%d: found %d matching candidates", category_id, len(results))
    return results


def fetch_candidates() -> List[Dict]:
    """Fetch matching candidates from Work.ua management/sales categories."""
    logger.info("Scraping Work.ua resumes (configs: %s)", CATEGORY_CONFIGS)
    all_results: List[Dict] = []
    seen_urls: set = set()

    with httpx.Client(headers=REQUEST_HEADERS, follow_redirects=True) as client:
        for cfg in CATEGORY_CONFIGS:
            for candidate in _scrape_category(client, cfg["id"], cfg["max_pages"]):
                if candidate["url"] not in seen_urls:
                    seen_urls.add(candidate["url"])
                    all_results.append(candidate)

    logger.info("Work.ua resumes total: %d unique matching candidates", len(all_results))
    return all_results
