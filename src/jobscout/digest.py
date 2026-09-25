"""Telegram message text (HTML parse mode). Pure functions, kept deliberately compact."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape

from jobscout.models import DigestRow

HINT = "Reply /save N, /applied N or /skip N"


def _closes(deadline: date | None) -> str:
    return f" · closes {deadline.strftime('%b')} {deadline.day}" if deadline else ""


def format_row(row: DigestRow) -> str:
    head = (
        f"#{row.num} <b>{escape(row.company)}</b>, {escape(row.title)}"
        f" · {row.fit}/10{_closes(row.deadline)}"
    )
    link = f'<a href="{escape(row.url, quote=True)}">link</a>'
    return f"{head}\n{escape(row.reason)} · {link}"


def format_digest(
    rows: Sequence[DigestRow],
    below: int,
    failed_scores: int,
    failed_sources: Sequence[str],
    min_fit: int,
) -> str:
    parts = ["<b>Jobs this week</b>"]
    if rows:
        parts.append("\n\n".join(format_row(r) for r in rows))
    else:
        parts.append("No new matches this week.")
    footer = []
    if below:
        footer.append(f"{below} more below {min_fit}")
    if failed_scores:
        footer.append(f"{failed_scores} couldn't be scored")
    if failed_sources:
        footer.append(f"failed: {', '.join(escape(s) for s in failed_sources)}")
    tail = [" · ".join(footer)] if footer else []
    if rows:
        tail.append(HINT)
    if tail:
        parts.append("\n".join(tail))
    return "\n\n".join(parts)


def format_urgent(row: DigestRow) -> str:
    return f"<b>Closes soon</b>\n{format_row(row)}"


def format_reminder(row: DigestRow, today: date) -> str:
    days = (row.deadline - today).days if row.deadline else 0
    when = {0: "today", 1: "tomorrow"}.get(days, f"in {days} days")
    return f"<b>Saved job closes {when}</b>\n{format_row(row)}"


def format_list(items: Sequence[tuple[DigestRow, str]]) -> str:
    if not items:
        return "Nothing saved or applied yet."
    sections = []
    for state, heading in (("saved", "Saved"), ("applied", "Applied")):
        lines = [
            f"#{row.num} {escape(row.company)}, {escape(row.title)}{_closes(row.deadline)}"
            for row, s in items
            if s == state
        ]
        if lines:
            sections.append(f"<b>{heading}</b>\n" + "\n".join(lines))
    return "\n\n".join(sections)
