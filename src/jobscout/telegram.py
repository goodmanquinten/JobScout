"""Minimal Telegram Bot API sender."""

from __future__ import annotations

import html
import re

import httpx

TELEGRAM_LIMIT = 4096
_API = "https://api.telegram.org"
_TAG = re.compile(r"<[^>]+>")


class TelegramError(Exception):
    """Raised when a message was not delivered."""


def visible_len(text: str) -> int:
    """Length as Telegram counts it: tags stripped, entities unescaped.

    The 4096-character limit applies after HTML entity parsing, so `<a href>`
    tags and their URLs cost nothing and `&amp;` counts as one character.
    """
    return len(html.unescape(_TAG.sub("", text)))


def _split_lines(para: str, limit: int) -> list[str]:
    """Pack single lines under `limit` visible characters.

    Only a line whose visible text is itself too long is hard-cut, and that cut
    is on raw characters (it may land inside a tag). A single line that long is
    pathological for our formatters, so the crude cut is accepted rather than
    parsing HTML here.
    """
    chunks: list[str] = []
    current = ""
    for line in para.split("\n"):
        while visible_len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else f"{current}\n{line}"
        if visible_len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on blank-line paragraph boundaries so no part exceeds `limit`.

    Lengths are measured as Telegram measures them (`visible_len`). A paragraph
    longer than the limit is split on line boundaries (so an `<a href>` tag is
    never cut in half); only a single line longer than the limit is hard-split.
    """
    if visible_len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if visible_len(para) > limit:
            if current:
                parts.append(current)
            chunks = _split_lines(para, limit)
            parts.extend(chunks[:-1])
            current = chunks[-1]
            continue
        candidate = para if not current else f"{current}\n\n{para}"
        if visible_len(candidate) > limit:
            parts.append(current)
            current = para
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def send_message(token: str, chat_id: str, text: str, timeout: float = 10.0) -> None:
    """Send `text` as one or more HTML-formatted messages. Raises TelegramError.

    Delivery is per part and not atomic: if part 2 of 3 fails, part 1 was already sent.
    """
    url = f"{_API}/bot{token}/sendMessage"
    for part in split_message(text):
        payload = {
            "chat_id": chat_id,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = httpx.post(url, json=payload, timeout=timeout)
        except httpx.HTTPError as exc:
            raise TelegramError(str(exc)) from exc
        if not resp.is_success:
            raise TelegramError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise TelegramError(f"non-JSON response: {resp.text[:200]}") from exc
        if not body.get("ok"):
            raise TelegramError(str(body.get("description", "unknown error")))


def get_updates(token: str, offset: int | None, timeout: float = 10.0) -> list[dict]:
    """New messages sent to the bot since `offset` (no long polling). Raises TelegramError."""
    params: dict[str, object] = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = httpx.get(f"{_API}/bot{token}/getUpdates", params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        raise TelegramError(str(exc)) from exc
    try:
        body = resp.json()
    except ValueError as exc:
        raise TelegramError(f"non-JSON response: {resp.text[:200]}") from exc
    if not body.get("ok"):
        raise TelegramError(str(body.get("description", f"HTTP {resp.status_code}")))
    return body.get("result", [])
