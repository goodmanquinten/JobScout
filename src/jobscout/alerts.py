"""Urgent pings (strong match closing soon) and reminders for saved jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time
from zoneinfo import ZoneInfo

from jobscout.digest import format_reminder, format_urgent
from jobscout.store import Store
from jobscout.telegram import TelegramError

log = logging.getLogger(__name__)

LISBON = ZoneInfo("Europe/Lisbon")
QUIET_START = time(23, 0)
QUIET_END = time(8, 0)
URGENT_FIT = 8
URGENT_DAYS = 7
REMINDER_DAYS = 3


def is_quiet(now: datetime) -> bool:
    local = now.astimezone(LISBON).time()
    return local >= QUIET_START or local < QUIET_END


def send_alerts(store: Store, send: Callable[[str], None], now: datetime) -> int:
    """Send pending pings and reminders. Returns how many were sent.

    An alert is recorded only after Telegram accepts it, so a failure or quiet
    hours leave it pending for the next run.
    """
    if is_quiet(now):
        return 0
    today = now.astimezone(LISBON).date()
    pending = [
        (row, "urgent", format_urgent(row))
        for row in store.urgent_candidates(today, URGENT_FIT, URGENT_DAYS)
    ] + [
        (row, "reminder", format_reminder(row, today))
        for row in store.reminder_candidates(today, REMINDER_DAYS)
    ]
    sent = 0
    for row, kind, text in pending:
        try:
            send(text)
        except TelegramError as exc:
            log.warning("alert not sent, will retry: %s", exc)
            break
        store.record_alert(row.job_id, kind, now)
        sent += 1
    return sent
