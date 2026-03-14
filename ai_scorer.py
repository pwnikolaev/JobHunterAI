import logging
import json
import re
from typing import Tuple

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CANDIDATE_PROFILE

# ── JAMM School vacancy profile for candidate scoring ─────────────────────────
JAMM_JOB_PROFILE = """
Вакансія: Керівник відділу продажів — JAMM School
Компанія: JAMM Group — 26 років на ринку, ліцензована дистанційна школа 5–11 класів (EdTech).
Формат: повністю remote, 5/2. Компенсація: ставка + KPI + бонуси.

Обов'язки:
- Побудова та управління відділом продажів
- Оптимізація воронки (ліди → консультації → зарахування)
- Контроль якості менеджерів (дзвінки, листування, консультації)
- Навчання, адаптація та мотивація команди
- Налаштування KPI, CRM, звітності
- Взаємодія з маркетингом (ліди, конверсії, гіпотези)

Обов'язкові вимоги:
- Досвід керівника відділу продажів від 2 років
- Знання воронок продажів, метрик, CRM, наскрізної аналітики
- Вміння працювати з довгим циклом угоди та теплими/холодними лідами
- Сильні управлінські навички, орієнтація на результат
- Грамотна мова, емпатія (клієнти — батьки дітей)

Переваги (не обов'язково):
- Досвід в онлайн-школі або EdTech
- Досвід масштабування відділу продажів з нуля
- Досвід B2B продажів
"""

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = """Ти — рекрутинговий асистент для пошуку вакансій топ-менеджерів IT.
Твоє завдання — детально проаналізувати відповідність вакансії профілю кандидата.

Профіль кандидата:
{profile}

Оціни вакансію за шкалою 0–100 де:
  0–39   = не відповідає
  40–64  = частково відповідає
  65–79  = добре відповідає
  80–100 = ідеально відповідає

Поверни ТІЛЬКИ JSON у форматі:
{{
  "score": <число від 0 до 100>,
  "tasks": [
    {{"name": "<назва функції або завдання з вакансії>", "status": "yes|partial|no"}},
    ...
  ],
  "skills": [
    {{"name": "<навичка або вимога з вакансії>", "has": true|false}},
    ...
  ]
}}

Правила:
- "tasks": витягни всі ключові функції та обов'язки з опису вакансії (5–10 пунктів).
  status = "yes" якщо кандидат має досвід, "partial" якщо частково, "no" якщо немає.
- "skills": витягни всі технічні та soft-вимоги (мови, інструменти, сертифікати, тощо, 5–12 пунктів).
  has = true якщо кандидат має цей навик, false якщо немає.
- Не додавай нічого поза JSON.
""".format(profile=CANDIDATE_PROFILE.strip())


def score_vacancy(
    title: str,
    company: str,
    description: str,
    location: str = "",
    salary: str = "",
) -> Tuple[int, str]:
    """
    Score a vacancy using Claude AI.

    Returns:
        Tuple of (score: int 0-100, comment: str in Ukrainian)
    """
    vacancy_text = f"""Назва вакансії: {title}
Компанія: {company}
Локація: {location}
Зарплата: {salary or 'не вказана'}
Опис:
{description[:3000]}
"""

    try:
        client = _get_client()
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Оціни цю вакансію:\n\n{vacancy_text}",
                }
            ],
        )
        raw = message.content[0].text.strip()

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in Claude response: {raw[:200]}")

        data = json.loads(json_match.group())
        score = max(0, min(100, int(data.get("score", 0))))

        # Format structured analysis into readable text
        lines = []

        tasks = data.get("tasks", [])
        if tasks:
            lines.append("📋 ФУНКЦІЇ ТА ЗАВДАННЯ:")
            for t in tasks:
                icon = {"yes": "✅", "partial": "⚡", "no": "❌"}.get(t.get("status"), "•")
                lines.append(f"  {icon}  {t.get('name', '')}")

        skills = data.get("skills", [])
        if skills:
            lines.append("")
            lines.append("🛠 НАВИЧКИ ТА ВИМОГИ:")
            for s in skills:
                icon = "✅" if s.get("has") else "❌"
                lines.append(f"  {icon}  {s.get('name', '')}")

        comment = "\n".join(lines).strip()
        logger.info("Scored '%s' → %d/100", title, score)
        return score, comment

    except anthropic.APIError as exc:
        logger.error("Anthropic API error: %s", exc)
        return 0, "Помилка API під час оцінки вакансії."
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse Claude response: %s", exc)
        return 0, "Не вдалося отримати оцінку від AI."
    except Exception as exc:
        logger.exception("Unexpected error in score_vacancy: %s", exc)
        return 0, "Невідома помилка під час оцінки."


# ── Candidate scorer ───────────────────────────────────────────────────────────

_CANDIDATE_SYSTEM_PROMPT = """Ти — рекрутинговий асистент, що допомагає підібрати кандидата на вакансію.
Твоє завдання — оцінити відповідність резюме кандидата до вакансії.

Вакансія:
{job_profile}

Оціни кандидата за шкалою 0–100 де:
  0–39   = не відповідає вимогам
  40–64  = частково відповідає
  65–79  = добре відповідає
  80–100 = ідеально відповідає

Поверни ТІЛЬКИ JSON у форматі:
{{
  "score": <число від 0 до 100>,
  "comment": "<короткий коментар українською, 2-3 речення, чому кандидат підходить або не підходить>"
}}

Не додавай нічого поза JSON.
""".format(job_profile=JAMM_JOB_PROFILE.strip())


def score_candidate(
    position: str,
    name: str,
    description: str,
    location: str = "",
    salary: str = "",
    experience: str = "",
) -> Tuple[int, str]:
    """
    Score a candidate resume using Claude AI against the JAMM School vacancy.

    Returns:
        Tuple of (score: int 0-100, comment: str in Ukrainian)
    """
    candidate_text = f"""Бажана посада: {position}
Ім'я: {name}
Локація: {location or 'не вказано'}
Зарплатні очікування: {salary or 'не вказано'}
Досвід: {experience or 'не вказано'}
Опис / навички:
{description[:3000]}
"""

    try:
        client = _get_client()
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=_CANDIDATE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Оціни цього кандидата:\n\n{candidate_text}",
                }
            ],
        )
        raw = message.content[0].text.strip()

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON in response: {raw[:200]}")

        data = json.loads(json_match.group())
        score = max(0, min(100, int(data.get("score", 0))))
        comment = str(data.get("comment", "")).strip()
        logger.info("Scored candidate '%s' → %d/100", position, score)
        return score, comment

    except anthropic.APIError as exc:
        logger.error("Anthropic API error scoring candidate: %s", exc)
        return 0, "Помилка API під час оцінки кандидата."
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse Claude response for candidate: %s", exc)
        return 0, "Не вдалося отримати оцінку від AI."
    except Exception as exc:
        logger.exception("Unexpected error in score_candidate: %s", exc)
        return 0, "Невідома помилка під час оцінки."
