"""Telegram replies: /save N, /applied N, /skip N, /list."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from jobscout.alerts import LISBON
from jobscout.digest import format_list, format_top
from jobscout.store import FRESH_DAYS, Store

HELP = "Commands: /top [N], /save N, /applied N, /skip N, /list"
DEFAULT_TOP = 20
MAX_TOP = 50
_STATES = {"save": "saved", "applied": "applied", "skip": "skipped"}
_COMMAND = re.compile(r"^/(save|applied|skip|list|top)(?:@\w+)?(?:\s+#?(\d+))?\s*$", re.I)


@dataclass(frozen=True)
class Command:
    name: str
    num: int | None


def parse_command(text: str) -> Command | None:
    m = _COMMAND.match(text.strip())
    if not m:
        return None
    return Command(m.group(1).lower(), int(m.group(2)) if m.group(2) else None)


def handle(store: Store, text: str, now: datetime) -> str:
    """Apply one command and return the reply text."""
    cmd = parse_command(text)
    if cmd is None:
        return HELP
    if cmd.name == "list":
        return format_list(store.saved_and_applied())
    if cmd.name == "top":
        limit = min(cmd.num or DEFAULT_TOP, MAX_TOP)
        since = now - timedelta(days=FRESH_DAYS)
        return format_top(store.top_scored(since, now.astimezone(LISBON).date(), limit))
    if cmd.num is None:
        return f"Usage: /{cmd.name} N"
    state = _STATES[cmd.name]
    job = store.set_status(cmd.num, state, now)
    if job is None:
        return f"No job #{cmd.num}."
    company, title = job
    return f"#{cmd.num} {escape(company)}, {escape(title)}: {state}"
