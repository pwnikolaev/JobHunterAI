"""
JobHunter AI — точка входу.

Запускає:
  1. Ініціалізацію бази даних
  2. Telegram-бот (async polling)
  3. Scheduler — кожні SCAN_INTERVAL_MINUTES хвилин запускає повний цикл:
       scrape → filter → AI score → Telegram notify
"""
import asyncio
import logging
import re
import sys
from datetime import datetime

from telegram.ext import Application

import db
from config import MIN_MATCH_SCORE, SCAN_INTERVAL_MINUTES, TARGET_LOCATIONS, EXCLUDED_LOCATIONS, SEARCH_KEYWORDS
from ai_scorer import score_vacancy
from bot import build_application, send_vacancies_batch

from scrapers import djinni, workua, dou, rabotaua, linkedin

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("jobhunter.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


# ──────────────────────────────────────────────
# Language filter
# ──────────────────────────────────────────────


MIN_UAH_SALARY = 150_000

PROJECT_KEYWORDS = [
    "проектна робота", "проектний", "project-based", "project based",
    "contract", "контракт", "підряд", "freelance", "фріланс",
    "тимчасова", "temporary", "short-term", "part-time",
]


def _parse_uah_max(salary_str: str) -> int | None:
    """
    Extract the maximum UAH value from a salary string.
    Returns None if salary is not in UAH or cannot be parsed.
    """
    if not salary_str:
        return None
    s = salary_str.lower().replace('\xa0', '').replace(' ', '')
    if 'грн' not in s and 'uah' not in s:
        return None
    numbers = [int(n) for n in re.findall(r'\d+', s) if len(n) >= 4]
    return max(numbers) if numbers else None


def is_salary_acceptable(vacancy: dict) -> bool:
    """
    Skip if: NOT project work AND UAH salary is specified and max value < 150,000 грн.
    Pass if: project work, salary >= 150,000 грн, non-UAH salary, or salary not specified.
    """
    text = (
        (vacancy.get("description") or "") + " " + (vacancy.get("title") or "")
    ).lower()

    # Project/contract work — always pass regardless of salary
    if any(kw in text for kw in PROJECT_KEYWORDS):
        return True

    uah_max = _parse_uah_max(vacancy.get("salary") or "")
    if uah_max is None:
        return True  # salary unknown or non-UAH — let through

    if uah_max < MIN_UAH_SALARY:
        logger.debug("Skipped (salary %d UAH < %d): %s", uah_max, MIN_UAH_SALARY, vacancy.get("title"))
        return False

    return True


def is_relevant_title(vacancy: dict) -> bool:
    """Returns True only if title or description contains at least one SEARCH_KEYWORD (whole-word match)."""
    text = (
        (vacancy.get("title") or "") + " " + (vacancy.get("description") or "")
    ).lower()
    return any(
        re.search(r'(?<![a-z])' + re.escape(kw.lower()) + r'(?![a-z])', text)
        for kw in SEARCH_KEYWORDS
    )


REMOTE_KEYWORDS = [
    "remote", "remotely", "fully remote",
    "дистанційно", "дистанційна", "дистанційний", "дистанц",
    "удалённо", "удалённая", "удалённый",
    "віддалено", "віддалена", "віддалений",
    "worldwide", "global", "anywhere",
]

# Office work is acceptable only in these countries
OFFICE_COUNTRIES = [
    # Italy
    "italy", "italia", "italien", "італія", "италия",
    "milan", "milano", "rome", "roma", "turin", "torino", "florence", "firenze",
    # Spain
    "spain", "españa", "іспанія", "испания",
    "madrid", "barcelona", "valencia", "seville", "sevilla",
    # Slovenia
    "slovenia", "словенія", "словения", "slowenien",
    "ljubljana",
    # Poland
    "poland", "polska", "польща", "польша",
    "warsaw", "warszawa", "kraków", "krakow", "wrocław", "wroclaw", "gdańsk", "gdansk",
    # Cyprus
    "cyprus", "кіпр", "кипр",
    "limassol", "nicosia", "paphos",
    # Ireland
    "ireland", "ірландія", "ирландия",
    "dublin",
]


def is_acceptable_work_location(vacancy: dict) -> bool:
    """
    Accept if: remote (anywhere), OR office in Italy/Spain/Slovenia/Poland/Cyprus/Ireland.
    Vacancies with no location are allowed (assumed remote/flexible).
    """
    location = (vacancy.get("location") or "").lower()
    description = (vacancy.get("description") or "").lower()
    full_text = location + " " + description

    if any(kw in full_text for kw in REMOTE_KEYWORDS):
        return True

    if not location.strip():
        return True  # no location info — assume flexible/remote

    if any(country in full_text for country in OFFICE_COUNTRIES):
        return True

    logger.debug("Skipped (location not remote or target country '%s'): %s", location, vacancy.get("title"))
    return False


def is_english_level_acceptable(vacancy: dict) -> bool:
    """
    Returns False if the vacancy explicitly requires English above B2 (C1, C2, native, fluent/advanced).
    Vacancies with no English requirement or B2 and below are allowed.
    Vacancies in English are allowed — only the required level is checked.
    """
    text = (
        (vacancy.get("description") or "") + " " + (vacancy.get("title") or "")
    ).lower()

    if not text.strip():
        return True

    above_b2_patterns = [
        # Level codes near "english"
        r'english\s*[:\-–—]\s*c[12]',
        r'c[12]\s+english',
        r'english\s+c[12]\b',
        # Native
        r'native\s+(?:english|speaker)',
        r'english\s*[:\-–—]\s*native',
        r'native\s+level\s+(?:of\s+)?english',
        # Fluent
        r'fluent\s+(?:in\s+)?english',
        r'english\s*[:\-–—]\s*fluent',
        r'english\s+fluency',
        # Advanced / Proficient (C1 equivalents)
        r'advanced\s+english',
        r'english\s*[:\-–—]\s*advanced',
        r'english\s+advanced',
        r'proficient\s+(?:in\s+)?english',
        r'english\s*[:\-–—]\s*proficient',
        # Ukrainian/Russian patterns
        r'англійськ\w*\s*[:\-–—]?\s*c[12]',
        r'англійськ\w*\s*[:\-–—]\s*(?:advanced|fluent|native|носій)',
        r'английск\w*\s*[:\-–—]?\s*c[12]',
        r'английск\w*\s*[:\-–—]\s*(?:advanced|fluent|native|носитель)',
        r'знання?\s+англійськ\w*\s+(?:на\s+рівні\s+)?c[12]',
        r'знание\s+английск\w*\s+(?:на\s+уровне\s+)?c[12]',
    ]

    for pattern in above_b2_patterns:
        if re.search(pattern, text):
            logger.debug("Skipped (English above B2): %s", vacancy.get("title"))
            return False

    return True


def is_acceptable_language(vacancy: dict) -> bool:
    """
    Accept if:
    - Vacancy description is in Russian or Ukrainian (Cyrillic dominant), OR
    - Vacancy is in English and does not require English above B2.
    """
    text = (vacancy.get("description") or "").strip()

    if not text:
        return True  # can't determine — let through

    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total = cyrillic + latin

    if total == 0:
        return True

    if cyrillic / total >= 0.5:
        return True  # RU/UA vacancy — always accept

    # English (or other) vacancy — check English level requirement
    if not is_english_level_acceptable(vacancy):
        logger.debug("Skipped (English vacancy, requires C1+): %s", vacancy.get("title"))
        return False

    return True


# ──────────────────────────────────────────────
# Scan cycle
# ──────────────────────────────────────────────

SCRAPERS = [
    ("Djinni", djinni.fetch_vacancies),
    ("DOU", dou.fetch_vacancies),
    ("Work.ua", workua.fetch_vacancies),
    ("Rabota.ua", rabotaua.fetch_vacancies),
    ("LinkedIn", linkedin.fetch_vacancies),
]


def run_scrapers() -> list:
    """Run all scrapers and return a flat list of vacancy dicts."""
    all_vacancies = []
    for name, fetcher in SCRAPERS:
        try:
            vacancies = fetcher()
            logger.info("%s returned %d vacancies", name, len(vacancies))
            all_vacancies.extend(vacancies)
        except Exception as exc:
            logger.exception("Scraper '%s' failed: %s", name, exc)
    return all_vacancies


def process_and_store(vacancies: list) -> list[int]:
    """
    For each new vacancy:
      1. Save to DB (skip duplicates).
      2. Run AI scoring.
      3. Update score in DB.
    Returns list of inserted vacancy IDs.
    """
    inserted_ids = []
    for v in vacancies:
        db.log_vacancy(
            source=v.get("source", ""),
            title=v.get("title", ""),
            url=v.get("url", ""),
            salary=v.get("salary", ""),
        )

        if not is_relevant_title(v):
            logger.debug("Skipped (irrelevant title): %s", v.get("title"))
            continue

        if not is_salary_acceptable(v):
            continue

        if not is_acceptable_work_location(v):
            continue

        if not is_acceptable_language(v):
            continue

        vacancy_id = db.insert_vacancy(
            title=v.get("title", ""),
            company=v.get("company", ""),
            url=v.get("url", ""),
            source=v.get("source", ""),
            salary=v.get("salary", ""),
            location=v.get("location", ""),
            description=v.get("description", ""),
        )
        if vacancy_id is None:
            continue  # duplicate

        logger.info("New vacancy #%d: %s @ %s", vacancy_id, v["title"], v["company"])

        # AI scoring
        score, comment = score_vacancy(
            title=v.get("title", ""),
            company=v.get("company", ""),
            description=v.get("description", ""),
            location=v.get("location", ""),
            salary=v.get("salary", ""),
        )
        db.update_score(vacancy_id, score, comment)
        inserted_ids.append(vacancy_id)

    return inserted_ids


async def scan_cycle(app: Application) -> None:
    """Full scan: scrape → store → score → send."""
    logger.info("=== Scan cycle started at %s ===", datetime.utcnow().isoformat())
    try:
        vacancies = run_scrapers()
        logger.info("Total raw vacancies fetched: %d", len(vacancies))

        new_ids = process_and_store(vacancies)
        logger.info("New vacancies processed: %d", len(new_ids))

        sent = await send_vacancies_batch(app.bot, min_score=MIN_MATCH_SCORE)
        logger.info("Vacancies sent to Telegram: %d", sent)

    except Exception as exc:
        logger.exception("Scan cycle error: %s", exc)

    logger.info("=== Scan cycle finished ===")


# ──────────────────────────────────────────────
# Scheduler (async)
# ──────────────────────────────────────────────

async def scheduler_loop(app: Application) -> None:
    """Run scan_cycle every SCAN_INTERVAL_MINUTES minutes."""
    interval_seconds = SCAN_INTERVAL_MINUTES * 60

    # Run immediately on startup
    await scan_cycle(app)

    while True:
        # Sleep in small increments so we can react to manual scan signals
        elapsed = 0
        while elapsed < interval_seconds:
            await asyncio.sleep(30)
            elapsed += 30

            # Check for manual scan request from /scan command
            if app.bot_data.get("manual_scan"):
                app.bot_data["manual_scan"] = False
                logger.info("Manual scan triggered via /scan command")
                await scan_cycle(app)
                elapsed = 0  # reset timer

        await scan_cycle(app)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

async def main_async() -> None:
    db.init_db()
    app = build_application()

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        logger.info(
            "JobHunter AI started. Scan interval: %d min. Min score: %d%%",
            SCAN_INTERVAL_MINUTES,
            MIN_MATCH_SCORE,
        )

        try:
            await scheduler_loop(app)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutting down...")
        finally:
            await app.updater.stop()
            await app.stop()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("JobHunter AI stopped by user.")


if __name__ == "__main__":
    main()
