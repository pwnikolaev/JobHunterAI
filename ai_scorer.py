import logging
import json
import re
from typing import Tuple

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CANDIDATE_PROFILE

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = """Ти — рекрутинговий асистент для пошуку вакансій топ-менеджерів IT.
Твоє завдання — оцінити відповідність вакансії профілю кандидата.

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
  "comment": "<короткий коментар українською, 2-3 речення, чому ця вакансія підходить або не підходить>"
}}

Не додавай нічого поза JSON.
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
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Оціни цю вакансію:\n\n{vacancy_text}",
                }
            ],
        )
        raw = message.content[0].text.strip()

        # Try to extract JSON even if there is extra text
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in Claude response: {raw[:200]}")

        data = json.loads(json_match.group())
        score = max(0, min(100, int(data.get("score", 0))))
        comment = str(data.get("comment", "")).strip()
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
