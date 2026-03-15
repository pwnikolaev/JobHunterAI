# JobHunter AI — Project Documentation

## Описание

**JobHunter AI** — интеллектуальный агент для поиска и ранжирования вакансий уровня CIO/CTO. Система автоматически сканирует несколько job-бордов, фильтрует вакансии по географии и языку, оценивает их с помощью Claude AI и отправляет наиболее релевантные в Telegram.

**Кандидат:** Павло Николаев, 14 лет опыта CIO/CTO, Польша, открыт к remote.

---

## Технологический стек

| Компонент | Технология |
|-----------|------------|
| Язык | Python 3.x |
| HTTP-клиент | httpx (async) |
| HTML-парсинг | BeautifulSoup4, lxml |
| RSS | feedparser |
| База данных | SQLite3 |
| AI-оценка | Anthropic Claude API (claude-sonnet-4-20250514) |
| Telegram | python-telegram-bot v21 |
| Web-дашборд | Flask 3.0 |
| Планировщик | schedule + asyncio |

---

## Структура проекта

```
job-agent/
├── main.py          — точка входа, цикл сканирования, фильтрация
├── bot.py           — Telegram бот: команды, колбэки, форматирование
├── ai_scorer.py     — интеграция с Claude API для оценки вакансий
├── db.py            — слой базы данных SQLite
├── config.py        — конфигурация: API-ключи, ключевые слова, гео
├── web.py           — Flask дашборд с live-сканированием
├── requirements.txt — зависимости Python
└── scrapers/
    ├── djinni.py    — Djinni.co (JSON API)
    ├── dou.py       — DOU.ua (RSS + HTML search)
    ├── workua.py    — Work.ua (HTML)
    ├── rabotaua.py  — Robota.ua (JSON API)
    └── linkedin.py  — LinkedIn Jobs (public HTML/JSON-LD)
```

---

## Возможности

### Источники вакансий
- **Djinni.co** — украинский IT job board, JSON API
- **DOU.ua** — украинский IT портал, RSS-лента + HTML-поиск по категориям
- **Work.ua** — украинский job board, парсинг HTML
- **Robota.ua** — украинский job board, JSON API
- **LinkedIn Jobs** — глобальный, публичный HTML без авторизации

### Фильтрация
- **Гео-фильтр**: пропускает Украину, ЕС, Кипр, remote; исключает США, Азию, Ближний Восток
- **Языковой фильтр**: кириллица > 50% букв (русский/украинский)
- **Ключевые слова**: CIO, CTO, Head of IT, IT Director, Digital Transformation, VP of Technology и др. (13 ролей)

### AI-оценка (Claude)
- Оценка соответствия вакансии профилю кандидата: 0–100
- Возвращает JSON: `{score, comment}` с пояснением на украинском
- Кэширование оценок в SQLite

### Telegram-бот
- `/start` — профиль кандидата
- `/status` — статистика базы данных
- `/scan` — немедленное сканирование
- `/settings` — текущие настройки
- Inline-кнопки: Откликнуться, Сохранить, Пропустить, Не підходить, Открыть ссылку
- Отправка вакансий с оценкой ≥ 65%

### Web-дашборд (Flask)
- Вкладка **"Лог вакансій"** — всі знайдені вакансії (сирі дані)
- Вкладка **"Оброблені AI"** — оцінені вакансії з фільтрами
- Вкладка **"👥 Кандидати"** — пошук резюме на Robota.ua та Work.ua під конкретну вакансію
- Окрема кнопка **"Знайти кандидатів"** з live-логом (незалежна від парсера вакансій)
- Фільтрація кандидатів: за джерелом, статусом (new/viewed/contacted/rejected), мінімальною оцінкою
- Кольорова індикація оцінок: зелений ≥75, жовтий 50–74, червоний <50
- Пагінація по 50 записів

### Конфигурация
- `MIN_MATCH_SCORE` — минимальный порог оценки для отправки (по умолчанию 65)
- `SCAN_INTERVAL_MINUTES` — интервал сканирования (по умолчанию 120 мин)

---

## Pipeline сканирования

```
run_scrapers()
  → process_and_store()
    → [гео-фильтр]
    → [языковой фильтр]
    → [фильтр по ключевым словам]
    → INSERT в vacancy_log (raw)
    → score_vacancy() через Claude API
    → UPDATE score в vacancies
  → send_vacancies_batch() → Telegram
```

---

## База данных (SQLite)

**Таблица `vacancies`** — обработанные вакансии:
- title, company, url, salary, location, description
- match_score, ai_comment, status, timestamps

**Таблица `vacancy_log`** — сырой лог сканирований:
- title, company, url, source, found_at
- Дедупликация по URL

---

## Changelog

### 2026-03-10 — Initial Release (commit: 9bb8034)
- Первоначальная реализация агента
- 5 scrapers: Djinni, DOU, Work.ua, Robota.ua, LinkedIn
- Telegram бот с базовыми командами
- Flask дашборд
- AI-оценка через Claude API

### 2026-03-13 — Candidate Search Tab (in progress)
- Нова вкладка **"Кандидати"** у web-дашборді
- `scrapers/candidates_robota.py` — парсер резюме Robota.ua (JSON API, пошук за ключовими словами)
- `scrapers/candidates_work.py` — парсер резюме Work.ua (HTML, до 3 сторінок результатів)
- `db.py` — таблиця `candidates` з полями: name, position, url, source, location, salary, experience, description, match_score, ai_comment, status, found_at
- `ai_scorer.py` — функція `score_candidate()` з профілем вакансії JAMM School (Керівник відділу продажів)
- Окремий scan state і кнопка "Знайти кандидатів" (незалежна від парсера вакансій)
- Фільтри: джерело, статус, мінімальна оцінка AI (≥50 / ≥65 / ≥80%)

### 2026-03-15 — DOU HTML scraping, статус "Не підходить", авто-порт
- **DOU скрапер**: добавлен HTML-парсинг страниц поиска (`?category=Management`, `?search=...`) в дополнение к RSS — теперь находит вакансии старше 1-2 дней
- **Статус "Не підходить"** (`rejected`): добавлен во все слои — Telegram-кнопка 🚫, дропдаун в дашборде (красная метка), статистика `/status`
- **web.py**: автоматический поиск свободного порта (5000–5100), исправлен `ALLOWED_STATUSES`

### 2026-03-10 — Scraper Fixes & Dashboard Improvements (commit: 2c10f98)
- Djinni переключён с RSS на JSON API (RSS давал 404)
- Work.ua переключён на категорийные страницы
- Robota.ua переключён на публичный JSON API
- LinkedIn: добавлены поиски по Украине и Кипру
- Уточнены языковой и гео-фильтры
- Web-дашборд: кнопка "Сканировать" с live-логом и статус-поллингом
