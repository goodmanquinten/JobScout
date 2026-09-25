"""Hourly run: answer commands, resend an unsent digest, send pings and reminders.

Run: uv run python -m jobscout.hourly
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

from jobscout.alerts import send_alerts
from jobscout.commands import handle
from jobscout.config import Settings
from jobscout.lock import LockBusy, file_lock
from jobscout.store import Store
from jobscout.telegram import TelegramError, get_updates, send_message
from jobscout.weekly import LOG_FORMAT

log = logging.getLogger(__name__)


def process_commands(
    store: Store, updates: list[dict], chat_id: str, reply: Callable[[str], None], now: datetime
) -> None:
    for u in updates:
        store.set_telegram_offset(u["update_id"] + 1)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id):
            continue
        text = msg.get("text") or ""
        if not text.startswith("/"):
            continue
        try:
            reply(handle(store, text, now))
        except TelegramError as exc:
            log.warning("reply not sent: %s", exc)


def resend_unsent(store: Store, send: Callable[[str], None], now: datetime) -> None:
    for digest_id, body in store.unsent_digests():
        try:
            send(body)
        except TelegramError as exc:
            log.warning("digest %s still unsent: %s", digest_id, exc)
            return
        store.mark_digest_sent(digest_id, now)


def run_hourly(
    store: Store,
    fetch_updates: Callable[[int | None], list[dict]],
    send: Callable[[str], None],
    chat_id: str,
    now: datetime,
) -> None:
    try:
        updates = fetch_updates(store.telegram_offset())
    except TelegramError as exc:
        log.warning("getUpdates failed: %s", exc)
        updates = []
    process_commands(store, updates, chat_id, send, now)
    resend_unsent(store, send, now)
    send_alerts(store, send, now)


def main() -> int:
    logging.basicConfig(filename="jobscout.log", level=logging.INFO, format=LOG_FORMAT)
    try:
        with file_lock():
            settings = Settings()
            run_hourly(
                Store.open(settings.db_path),
                partial(get_updates, settings.telegram_bot_token),
                partial(send_message, settings.telegram_bot_token, settings.telegram_chat_id),
                settings.telegram_chat_id,
                datetime.now(UTC),
            )
    except LockBusy:
        log.info("another run holds the lock; skipping")
        return 0
    except Exception:
        log.exception("hourly run failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
