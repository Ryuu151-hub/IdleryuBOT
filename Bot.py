"""
Telegram bot: lets a user (re)generate a personal bot-side ID code,
but only if they are a member of a required Telegram group.

Note: A real Telegram user_id is permanent and can never be changed by
anyone, including the user. What this bot regenerates is a unique code
that YOUR bot/database associates with that user (e.g. for referrals,
invite tracking, redeem codes, etc.).

Setup:
    1. pip install -r requirements.txt
    2. Set the BOT_TOKEN environment variable (token from @BotFather)
    3. Add this bot to your group (https://t.me/loverielle76) as a
       member — admin rights are recommended for reliable status checks
    4. python bot.py
"""

import logging
import os
import secrets
import sqlite3
import string
from contextlib import closing
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("8900764577:AAEG69GaERLjaqC0khhUYEuM7HkV4V9psFs", "")
# Username form works for get_chat_member on public groups/channels.
GROUP_USERNAME = "@loverielle76"
GROUP_LINK = "https://t.me/loverielle76"
DB_PATH = os.environ.get("BOT_DB_PATH", "users.db")
CODE_LENGTH = 10

# Statuses that count as "still in the group"
JOINED_STATUSES = {"member", "administrator", "creator", "restricted"}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("id_bot")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                code        TEXT UNIQUE NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _generate_candidate(length: int = CODE_LENGTH) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def get_user_code(user_id: int) -> str | None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT code FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def set_new_code(user_id: int, username: str | None) -> str:
    """Generate a fresh unique code and store it for this user."""
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        while True:
            code = _generate_candidate()
            exists = conn.execute(
                "SELECT 1 FROM users WHERE code = ?", (code,)
            ).fetchone()
            if not exists:
                break
        conn.execute(
            """
            INSERT INTO users (user_id, username, code, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                code       = excluded.code,
                updated_at = excluded.updated_at
            """,
            (user_id, username or "", code, now),
        )
        conn.commit()
    return code


# ---------------------------------------------------------------------------
# Membership check
# ---------------------------------------------------------------------------

async def is_group_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=GROUP_USERNAME, user_id=user_id
        )
        return member.status in JOINED_STATUSES
    except TelegramError as exc:
        # Common causes: bot not in the group, user never started a chat
        # with the bot, or user_id has never interacted with that group.
        logger.warning("Membership check failed for %s: %s", user_id, exc)
        return False


def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join the group", url=GROUP_LINK)],
            [InlineKeyboardButton("✅ I've joined — check again", callback_data="check_join")],
        ]
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome! 👋\n\n"
        "/myid — show your current ID\n"
        "/regenerate — get a new ID (requires joining our group)"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    code = get_user_code(user.id)
    if code:
        await update.message.reply_text(f"Your current ID: `{code}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "You don't have an ID yet. Use /regenerate to create one."
        )


async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not await is_group_member(context, user.id):
        await update.message.reply_text(
            "🚫 You need to join our group before you can regenerate your ID.",
            reply_markup=join_keyboard(),
        )
        return

    code = set_new_code(user.id, user.username)
    await update.message.reply_text(f"✅ Your new ID: `{code}`", parse_mode="Markdown")


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    if await is_group_member(context, user.id):
        await query.answer("Verified! You can now use /regenerate.", show_alert=True)
    else:
        await query.answer("You haven't joined the group yet.", show_alert=True)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN environment variable is not set. "
            "Get a token from @BotFather and set it before running."
        )

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("regenerate", regenerate))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_error_handler(on_error)

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
