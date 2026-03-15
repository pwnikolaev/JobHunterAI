import sqlite3
import logging
from datetime import datetime
from typing import Optional

DB_PATH = "jobhunter.db"
logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                company     TEXT,
                url         TEXT UNIQUE NOT NULL,
                source      TEXT,
                salary      TEXT,
                location    TEXT,
                description TEXT,
                match_score INTEGER DEFAULT 0,
                ai_comment  TEXT,
                status      TEXT DEFAULT 'new',
                found_at    TEXT,
                sent_at     TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_url ON vacancies (url)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON vacancies (status)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vacancy_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,
                title       TEXT NOT NULL,
                url         TEXT UNIQUE NOT NULL,
                salary      TEXT,
                scraped_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_log_scraped_at ON vacancy_log (scraped_at)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT,
                position    TEXT NOT NULL,
                url         TEXT UNIQUE NOT NULL,
                source      TEXT,
                location    TEXT,
                salary      TEXT,
                experience  TEXT,
                description TEXT,
                match_score INTEGER DEFAULT 0,
                ai_comment  TEXT,
                status      TEXT DEFAULT 'new',
                found_at    TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_candidate_url ON candidates (url)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidates (status)
        """)
        conn.commit()
    logger.info("Database initialised at %s", DB_PATH)


def vacancy_exists(url: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM vacancies WHERE url = ?", (url,)
        ).fetchone()
        return row is not None


def insert_vacancy(
    title: str,
    company: str,
    url: str,
    source: str,
    salary: str = "",
    location: str = "",
    description: str = "",
    match_score: int = 0,
    ai_comment: str = "",
    status: str = "new",
) -> Optional[int]:
    """Insert a new vacancy. Returns the new row id, or None if duplicate."""
    if vacancy_exists(url):
        return None
    found_at = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO vacancies
                (title, company, url, source, salary, location,
                 description, match_score, ai_comment, status, found_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, company, url, source, salary, location,
             description, match_score, ai_comment, status, found_at),
        )
        conn.commit()
        return cur.lastrowid


def update_score(vacancy_id: int, score: int, comment: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE vacancies SET match_score = ?, ai_comment = ? WHERE id = ?",
            (score, comment, vacancy_id),
        )
        conn.commit()


def mark_sent(vacancy_id: int) -> None:
    sent_at = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE vacancies SET status = 'sent', sent_at = ? WHERE id = ?",
            (sent_at, vacancy_id),
        )
        conn.commit()


def update_status(vacancy_id: int, status: str) -> None:
    """Set status: new | sent | applied | saved | skipped."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE vacancies SET status = ? WHERE id = ?",
            (status, vacancy_id),
        )
        conn.commit()


def get_vacancy_by_id(vacancy_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)
        ).fetchone()


def get_pending_vacancies(min_score: int = 0):
    """Return vacancies that have been scored but not yet sent."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM vacancies
            WHERE status = 'new' AND match_score >= ?
            ORDER BY match_score DESC
            """,
            (min_score,),
        ).fetchall()


def log_vacancy(source: str, title: str, url: str, salary: str = "") -> None:
    """Write scraped vacancy to the log table. Skips if URL already exists."""
    scraped_at = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vacancy_log (source, title, url, salary, scraped_at) VALUES (?, ?, ?, ?, ?)",
            (source, title, url, salary, scraped_at),
        )
        conn.commit()


# ── Candidates ────────────────────────────────────────────────────────────────

def candidate_exists(url: str) -> bool:
    with get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM candidates WHERE url = ?", (url,)
        ).fetchone() is not None


def insert_candidate(
    name: str,
    position: str,
    url: str,
    source: str,
    location: str = "",
    salary: str = "",
    experience: str = "",
    description: str = "",
    match_score: int = 0,
    ai_comment: str = "",
    status: str = "new",
) -> Optional[int]:
    """Insert a new candidate. Returns new row id, or None if duplicate."""
    if candidate_exists(url):
        return None
    found_at = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO candidates
                (name, position, url, source, location, salary, experience,
                 description, match_score, ai_comment, status, found_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, position, url, source, location, salary, experience,
             description, match_score, ai_comment, status, found_at),
        )
        conn.commit()
        return cur.lastrowid


def update_candidate_score(candidate_id: int, score: int, comment: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE candidates SET match_score = ?, ai_comment = ? WHERE id = ?",
            (score, comment, candidate_id),
        )
        conn.commit()


def update_candidate_status(candidate_id: int, status: str) -> None:
    """Set status: new | viewed | contacted | rejected."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE candidates SET status = ? WHERE id = ?",
            (status, candidate_id),
        )
        conn.commit()


def get_candidate_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        viewed = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE status = 'viewed'"
        ).fetchone()[0]
        contacted = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE status = 'contacted'"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE status = 'rejected'"
        ).fetchone()[0]
        avg_score = conn.execute(
            "SELECT AVG(match_score) FROM candidates WHERE match_score > 0"
        ).fetchone()[0]
    return {
        "total": total,
        "viewed": viewed,
        "contacted": contacted,
        "rejected": rejected,
        "avg_score": round(avg_score or 0, 1),
    }


def get_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        sent = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE status = 'sent'"
        ).fetchone()[0]
        applied = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE status = 'applied'"
        ).fetchone()[0]
        saved = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE status = 'saved'"
        ).fetchone()[0]
        skipped = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE status = 'skipped'"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE status = 'rejected'"
        ).fetchone()[0]
        avg_score = conn.execute(
            "SELECT AVG(match_score) FROM vacancies WHERE match_score > 0"
        ).fetchone()[0]
    return {
        "total": total,
        "sent": sent,
        "applied": applied,
        "saved": saved,
        "skipped": skipped,
        "rejected": rejected,
        "avg_score": round(avg_score or 0, 1),
    }
