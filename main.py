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
from config import MIN_MATCH_SCORE, SCAN_INTERVAL_MINUTES, TARGET_LOCATIONS, EXCLUDED_LOCATIONS
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

# Patterns that indicate required English level is above B2
_ENGLISH_TOO_HIGH = re.compile(
    r'\b(C[12]|native(\s+speaker)?|advanced\s+english|proficient\s+english|'
    r'fluent\s+(in\s+)?english|english\s+(at\s+)?C[12]|upper[\s-]advanced)\b',
    re.IGNORECASE,
)


def _is_cyrillic_dominant(text: str) -> bool:
    """True if the text is predominantly Cyrillic (Russian or Ukrainian)."""
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    return cyrillic > latin * 0.4  # at least ~29% Cyrillic vs Latin


def is_acceptable_location(vacancy: dict) -> bool:
    """
    Returns False (skip) if location is explicitly outside target regions.
    Vacancies with empty location are allowed (likely remote).
    """
    location = (vacancy.get("location") or "").lower()

    if not location:
        return True  # no location = remote, allow

    # Reject if explicitly excluded region
    if any(excl in location for excl in EXCLUDED_LOCATIONS):
        logger.debug("Skipped (excluded location '%s'): %s", location, vacancy.get("title"))
        return False

    # If location is specified, it must match at least one target
    # Exception: sources that are inherently local (Work.ua, Robota.ua, DOU) — always allow
    if vacancy.get("source") in ("Work.ua", "Robota.ua", "DOU", "Djinni"):
        return True

    if any(tgt in location for tgt in TARGET_LOCATIONS):
        return True

    # Unknown location from LinkedIn/other — skip to avoid noise
    logger.debug("Skipped (non-target location '%s'): %s", location, vacancy.get("title"))
    return False


def is_acceptable_language(vacancy: dict) -> bool:
    """
    Returns False (skip) if:
    - The vacancy language is not RU/UA/EN (e.g. Polish, German, etc.)
    - The description explicitly requires C1/C2/native English
    """
    text = " ".join(filter(None, [
        vacancy.get("title", ""),
        vacancy.get("description", ""),
    ]))

    # Detect vacancy language: accept Cyrillic (RU/UA) or Latin (EN)
    # Reject if text is Latin but not English-like (heuristic: non-English words)
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total = cyrillic + latin

    if total == 0:
        return True  # can't determine, let it through

    # If less than 5% Cyrillic AND less than 60% Latin → likely non-EN/RU/UA language
    cyrillic_ratio = cyrillic / total
    latin_ratio = latin / total
    if cyrillic_ratio < 0.05 and latin_ratio < 0.6:
        logger.debug("Skipped (non-target language): %s", vacancy.get("title"))
        return False

    # Check for C1/C2/native English requirement
    if _ENGLISH_TOO_HIGH.search(text):
        logger.debug("Skipped (English level too high): %s", vacancy.get("title"))
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

        if not is_acceptable_location(v):
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
