"""
Telegram bot for JobHunter AI.

Commands:
  /start    — welcome message
  /status   — statistics from DB
  /scan     — trigger manual scan
  /settings — show current settings

Inline buttons per vacancy:
  ✅ Відгукнутись  |  💾 Зберегти  |  ❌ Пропустити  |  🔗 Відкрити вакансію
"""
import logging
from typing import Optional

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import db
from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    MIN_MATCH_SCORE,
    SCAN_INTERVAL_MINUTES,
    SEARCH_KEYWORDS,
    CANDIDATE_NAME,
    CANDIDATE_LOCATION,
    CANDIDATE_WORK_FORMAT,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Vacancy message formatting
# ──────────────────────────────────────────────

def _score_emoji(score: int) -> str:
    if score >= 80:
        return "🟢"
    if score >= 65:
        return "🟡"
    return "🔴"


def format_vacancy_message(vacancy: db.sqlite3.Row) -> str:
    score = vacancy["match_score"]
    emoji = _score_emoji(score)
    salary = vacancy["salary"] or "не вказана"
    location = vacancy["location"] or "не вказана"
    comment = vacancy["ai_comment"] or ""
    source = vacancy["source"] or ""

    lines = [
        f"{emoji} *{_escape(vacancy['title'])}*",
        f"🏢 {_escape(vacancy['company'] or '—')}",
        f"📍 {_escape(location)}",
        f"💰 {_escape(salary)}",
        f"📊 Відповідність: *{score}/100*",
        f"🤖 _{_escape(comment)}_",
        f"🔗 Джерело: `{source}`",
    ]
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape special MarkdownV2 characters."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def build_vacancy_keyboard(vacancy_id: int, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Відгукнутись", callback_data=f"apply:{vacancy_id}"),
            InlineKeyboardButton("💾 Зберегти", callback_data=f"save:{vacancy_id}"),
        ],
        [
            InlineKeyboardButton("❌ Пропустити", callback_data=f"skip:{vacancy_id}"),
            InlineKeyboardButton("🔗 Відкрити вакансію", url=url),
        ],
    ])


# ──────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *JobHunter AI* — агент пошуку вакансій CIO/CTO\n\n"
        f"Кандидат: *{CANDIDATE_NAME}*\n"
        f"Локація: {CANDIDATE_LOCATION} | Формат: {CANDIDATE_WORK_FORMAT}\n\n"
        "Доступні команди:\n"
        "/status — статистика вакансій\n"
        "/scan — запустити сканування зараз\n"
        "/settings — поточні налаштування"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = db.get_stats()
    text = (
        "📊 *Статистика JobHunter AI*\n\n"
        f"Всього знайдено: `{stats['total']}`\n"
        f"Відправлено: `{stats['sent']}`\n"
        f"Відгукнувся: `{stats['applied']}`\n"
        f"Збережено: `{stats['saved']}`\n"
        f"Пропущено: `{stats['skipped']}`\n"
        f"Середній score: `{stats['avg_score']}/100`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔍 Запускаю сканування вакансій...\n"
        "Результати з'являться у чаті через кілька хвилин."
    )
    # Signal to main.py to run a scan cycle
    # This is done via context.bot_data flag checked by the scheduler
    context.bot_data["manual_scan"] = True


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keywords = "\n".join(f"  • {kw}" for kw in SEARCH_KEYWORDS)
    text = (
        "⚙️ *Поточні налаштування*\n\n"
        f"Мін. відповідність: `{MIN_MATCH_SCORE}%`\n"
        f"Інтервал сканування: `{SCAN_INTERVAL_MINUTES} хв`\n\n"
        f"Ключові слова:\n{keywords}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# Callback query handler (inline buttons)
# ──────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    action, vacancy_id_str = data.split(":", 1)
    try:
        vacancy_id = int(vacancy_id_str)
    except ValueError:
        return

    vacancy = db.get_vacancy_by_id(vacancy_id)
    if not vacancy:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if action == "apply":
        db.update_status(vacancy_id, "applied")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"✅ Вакансію *{vacancy['title']}* відмічено як «Відгукнувся».\n"
            f"Посилання: {vacancy['url']}",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "save":
        db.update_status(vacancy_id, "saved")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"💾 Вакансію *{vacancy['title']}* збережено.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "skip":
        db.update_status(vacancy_id, "skipped")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"❌ Вакансію *{vacancy['title']}* пропущено.",
            parse_mode=ParseMode.MARKDOWN,
        )


# ──────────────────────────────────────────────
# Sending vacancies
# ──────────────────────────────────────────────

async def send_vacancy(bot: Bot, vacancy: db.sqlite3.Row) -> None:
    """Send a single vacancy card to the configured chat."""
    try:
        text = format_vacancy_message(vacancy)
        keyboard = build_vacancy_keyboard(vacancy["id"], vacancy["url"])
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        db.mark_sent(vacancy["id"])
        logger.info("Sent vacancy #%d '%s' to Telegram", vacancy["id"], vacancy["title"])
    except Exception as exc:
        logger.error("Failed to send vacancy #%d: %s", vacancy["id"], exc)


async def send_vacancies_batch(bot: Bot, min_score: int = MIN_MATCH_SCORE) -> int:
    """Send all pending high-score vacancies. Returns count sent."""
    pending = db.get_pending_vacancies(min_score=min_score)
    for v in pending:
        await send_vacancy(bot, v)
    return len(pending)


# ──────────────────────────────────────────────
# Application factory
# ──────────────────────────────────────────────

def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app
