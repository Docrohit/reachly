"""Telegram bot used for sign-up + OTP login.

Flow:
  1. User opens the bot in Telegram and sends /start.
     -> the poller upserts a User row (keyed by their chat id) and replies with
        their Reachly handle (username or numeric id).
  2. On the website the user enters that handle and clicks "Send code".
     -> the server generates a 6-digit OTP and the bot DMs it to them.
  3. User enters the OTP -> authenticated session.

The poller runs in a background thread (long-polling getUpdates), so no public
webhook is required — it works on any machine, including behind NAT.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import datetime, timedelta

import requests
from sqlmodel import select

from .db import OtpRow, User, get_session
from .settings import get_settings

logger = logging.getLogger("reachly.telegram")

OTP_TTL_MINUTES = 10


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    # ---- messaging ----------------------------------------------------
    def send_message(self, chat_id: str | int, text: str) -> bool:
        try:
            r = requests.post(
                f"{self.base}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=20,
            )
            return r.ok
        except Exception as e:  # noqa: BLE001
            logger.warning("Telegram sendMessage failed: %s", e)
            return False

    # ---- polling ------------------------------------------------------
    def poll_forever(self, stop: threading.Event | None = None) -> None:
        offset = 0
        logger.info("Telegram poller started.")
        while not (stop and stop.is_set()):
            try:
                r = requests.get(
                    f"{self.base}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                    timeout=40,
                )
                if not r.ok:
                    time.sleep(3)
                    continue
                for update in r.json().get("result", []):
                    offset = update["update_id"] + 1
                    self._handle_update(update)
            except Exception as e:  # noqa: BLE001
                logger.warning("Telegram poll error: %s", e)
                time.sleep(5)

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id"))
        username = chat.get("username")
        text = (msg.get("text") or "").strip()

        if text.startswith("/start"):
            self._on_start(chat_id, username)

    def _on_start(self, chat_id: str, username: str | None) -> None:
        settings = get_settings()
        is_admin = chat_id in settings.admin_telegram_ids
        is_active = settings.free_mode or is_admin
        with get_session() as session:
            user = session.exec(select(User).where(User.telegram_chat_id == chat_id)).first()
            if not user:
                user = User(
                    telegram_chat_id=chat_id,
                    telegram_username=username,
                    is_active=is_active,
                    plan="pro" if is_admin else "free",
                    dry_run=True,
                )
                session.add(user)
            else:
                user.telegram_username = username or user.telegram_username
                if is_admin:
                    user.is_active = True
                    user.plan = "pro"
                session.add(user)
            session.commit()

        handle = f"@{username}" if username else chat_id
        self.send_message(
            chat_id,
            "👋 Welcome to <b>Reachly</b> — your daily thought-leadership autopilot.\n\n"
            f"Your login handle is: <b>{handle}</b>\n"
            f"(or your numeric ID: <code>{chat_id}</code>)\n\n"
            "Go back to the website, enter this handle, and we'll send you a login code here.",
        )


# ---- OTP helpers ------------------------------------------------------
def generate_and_send_otp(handle: str) -> tuple[bool, str]:
    """Look up a user by @username or numeric id, send them an OTP.
    Returns (ok, message)."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        return False, "Telegram bot is not configured on the server."

    handle = handle.strip().lstrip("@")
    with get_session() as session:
        user = session.exec(
            select(User).where(
                (User.telegram_username == handle) | (User.telegram_chat_id == handle)
            )
        ).first()
        if not user:
            return False, "We couldn't find you. Open the bot and send /start first."

        code = f"{secrets.randbelow(1_000_000):06d}"
        session.add(
            OtpRow(
                telegram_chat_id=user.telegram_chat_id,
                code=code,
                expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
            )
        )
        session.commit()
        chat_id = user.telegram_chat_id

    bot = TelegramBot(settings.telegram_bot_token)
    ok = bot.send_message(
        chat_id,
        f"🔐 Your Reachly login code is <b>{code}</b>\n"
        f"It expires in {OTP_TTL_MINUTES} minutes.",
    )
    if not ok:
        return False, "Failed to send the code via Telegram."
    return True, "Code sent! Check your Telegram."


def verify_otp(handle: str, code: str) -> tuple[bool, int | None]:
    """Verify an OTP; returns (ok, user_id)."""
    handle = handle.strip().lstrip("@")
    with get_session() as session:
        user = session.exec(
            select(User).where(
                (User.telegram_username == handle) | (User.telegram_chat_id == handle)
            )
        ).first()
        if not user:
            return False, None
        otp = session.exec(
            select(OtpRow)
            .where(OtpRow.telegram_chat_id == user.telegram_chat_id)
            .where(OtpRow.consumed == False)  # noqa: E712
            .order_by(OtpRow.id.desc())
        ).first()
        if not otp or otp.code != code.strip():
            return False, None
        if otp.expires_at < datetime.utcnow():
            return False, None
        otp.consumed = True
        session.add(otp)
        session.commit()
        return True, user.id


def start_bot_thread() -> threading.Thread | None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("REACHLY_TELEGRAM_BOT_TOKEN not set — OTP login disabled.")
        return None
    bot = TelegramBot(settings.telegram_bot_token)
    t = threading.Thread(target=bot.poll_forever, daemon=True, name="telegram-poller")
    t.start()
    return t
