import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Candidate profile
CANDIDATE_NAME = "Pavlo Nikolaiev"
CANDIDATE_EXPERIENCE_YEARS = 14
CANDIDATE_LOCATION = "Poland"
CANDIDATE_WORK_FORMAT = "remote"
CANDIDATE_PROFILE = """
Senior IT Executive with 14 years of experience as CIO/CTO.
Based in Poland, open to remote work globally.
Expertise: IT strategy, digital transformation, team leadership,
enterprise architecture, cloud infrastructure, automation, AI integration.
"""

# Search keywords (any of these must appear in title or description)
SEARCH_KEYWORDS = [
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

# Minimum AI match score to notify via Telegram (0–100)
MIN_MATCH_SCORE = 65

# How often to scan for new jobs (minutes)
SCAN_INTERVAL_MINUTES = 120

# HTTP request settings
REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8,pl;q=0.7",
}

# Scraper URLs
DJINNI_RSS = "https://djinni.co/jobs/feed/"
DOU_RSS = "https://jobs.dou.ua/vacancies/feeds/"
WORKUA_URL = "https://www.work.ua/jobs/"
RABOTAUA_URL = "https://rabota.ua/vacancies/"
LINKEDIN_URL = "https://www.linkedin.com/jobs/search/"

# Work.ua search URL for executive IT roles
WORKUA_SEARCH_URL = "https://www.work.ua/jobs/?q=CIO+CTO+Head+of+IT&employment=3"

# Rabota.ua search URL
RABOTAUA_SEARCH_URL = (
    "https://rabota.ua/zapros/cio%20cto%20head%20of%20it/ukraine"
)

# LinkedIn public search (no auth)
LINKEDIN_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/?keywords=CIO+CTO+Head+of+IT"
    "&location=Poland&f_WT=2&f_TPR=r604800"
)

# Target geographies for vacancy filtering
# Vacancies must be in one of these regions (or remote/not specified)
TARGET_LOCATIONS = [
    # Ukraine
    "ukraine", "україна", "украина",
    "kyiv", "київ", "киев",
    "lviv", "львів", "харків", "одеса", "дніпро",
    # Europe
    "europe", "европа", "євро",
    "poland", "польща", "польша",
    "germany", "germany", "deutschland", "німеччина",
    "czech", "czechia", "чехія",
    "slovakia", "словаків",
    "netherlands", "нідерланди",
    "austria", "австрія",
    "switzerland", "швейцарія",
    "france", "франція",
    "spain", "іспанія",
    "italy", "italien", "італія",
    "portugal",
    "romania", "румунія",
    "hungary", "угорщина",
    "bulgaria", "болгарія",
    "croatia", "хорватія",
    "lithuania", "latvia", "estonia",
    # Cyprus
    "cyprus", "кіпр", "кипр",
    "limassol", "nicosia", "paphos",
    # Remote
    "remote", "worldwide", "global", "anywhere",
    "дистанційно", "удалённо", "віддалено",
]

# Locations that indicate vacancy is NOT in target region — skip
EXCLUDED_LOCATIONS = [
    "united states", "usa", "u.s.a", "us only",
    "canada", "australia", "new zealand",
    "india", "china", "japan", "singapore", "hong kong",
    "dubai", "uae", "saudi", "qatar",
    "brazil", "argentina", "mexico",
    "south africa",
]

# Claude model
CLAUDE_MODEL = "claude-sonnet-4-20250514"
