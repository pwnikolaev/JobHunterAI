# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

JobHunter AI is an automated job aggregation system that scrapes 5 Ukrainian/international job boards (Djinni, DOU, Work.ua, Robota.ua, LinkedIn), filters vacancies, scores them with Claude AI against a candidate profile, and sends matches via Telegram. It also has a Flask web dashboard and a reverse candidate search feature.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Start the main agent (Telegram bot + scheduler, runs every 2 hours)
python main.py

# Start the web dashboard (separate process, port 5000)
python web.py
```

No test suite or linter configuration exists in this project.

## Configuration

- **`.env`** — API keys: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`
- **`config.py`** — All hardcoded settings: candidate profile, search keywords, salary thresholds, target locations, Claude model ID, scan interval

## Architecture

### Scan Cycle (`main.py`)
The core loop runs every `SCAN_INTERVAL_MINUTES` (default 120):
1. `run_scrapers()` — Calls all 5 scrapers concurrently via `httpx`
2. `process_and_store()` — Applies filter pipeline, inserts to DB, calls AI scorer
3. `send_vacancies_batch()` — Sends qualifying vacancies (score ≥ `MIN_MATCH_SCORE`) to Telegram

### Filter Pipeline (`main.py`)
Applied in order before AI scoring:
- `is_relevant_title()` — regex keyword match against `SEARCH_KEYWORDS`
- `is_salary_acceptable()` — skip UAH < 150k (unless contract/project)
- `is_acceptable_work_location()` — must be remote or in `TARGET_LOCATIONS`
- `is_english_level_acceptable()` — skip C1+/native/fluent requirements
- `is_acceptable_language()` — >50% Cyrillic OR English without C1+ requirement

### Component Map
| File | Responsibility |
|------|---------------|
| `main.py` | Orchestration, filtering pipeline, scan cycle |
| `bot.py` | Telegram bot, inline buttons (Apply/Save/Skip), status updates |
| `ai_scorer.py` | Claude API calls, structured scoring output in Ukrainian |
| `db.py` | SQLite layer for `vacancies`, `vacancy_log`, `candidates` tables |
| `config.py` | All tunable constants (candidate profile, keywords, thresholds) |
| `web.py` | Flask dashboard (vacancy log, AI-processed list, candidate search) |
| `scrapers/*.py` | One scraper per job board; each returns `List[Dict]` with keys: `title`, `company`, `url`, `source`, `salary`, `location`, `description` |

### Database (`jobhunter.db`)
- **`vacancies`** — Filtered, scored vacancies; `url` is unique key; has `match_score`, `ai_comment`, `status`
- **`vacancy_log`** — Raw scraped URLs for deduplication across scans
- **`candidates`** — Resume data from Robota.ua & Work.ua for reverse search

### AI Scoring (`ai_scorer.py`)
Uses `claude-sonnet-4-20250514` (set in `config.py` as `CLAUDE_MODEL`). Produces:
- Score 0–100
- List of tasks with `yes/partial/no` status
- List of skills/requirements with `has: true/false`
- Formatted comment in Ukrainian

### Telegram Bot (`bot.py`)
- Commands: `/start`, `/status`, `/scan`, `/settings`
- Score display: 🟢≥80, 🟡≥65, 🔴<65
- Vacancy statuses: `new → sent → applied/saved/skipped`

### Web Dashboard (`web.py`)
- Three tabs: vacancy log, AI-processed vacancies, candidate search
- Live scan with streamed log output
- Filtering by source/status/score, pagination (50/page)
- Runs independently from `main.py` (has its own scan runner)
