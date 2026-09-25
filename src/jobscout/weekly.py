"""Weekly run: fetch, filter, score, send the digest.

Run: uv run python -m jobscout.weekly
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx

from jobscout.alerts import LISBON, send_alerts
from jobscout.config import Profile, Settings, Watchlist, load_watchlist
from jobscout.digest import format_digest
from jobscout.filter import apply_rules
from jobscout.lock import LockBusy, file_lock
from jobscout.models import Posting, Score
from jobscout.score import ClaudeScorer, ScoreError, make_client
from jobscout.sources.ats import USER_AGENT, SourceError, fetch_company
from jobscout.sources.handshake_mail import fetch_handshake
from jobscout.store import Store
from jobscout.telegram import TelegramError, send_message

log = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MIN_FIT = 6
DIGEST_SIZE = 8
FRESH_DAYS = 8


@dataclass(frozen=True)
class Source:
    name: str
    fetch: Callable[[], list[Posting]]
    allow_non_us: bool = False
    title_include: tuple[str, ...] = ()


def run_weekly(
    store: Store,
    sources: list[Source],
    score: Callable[[Posting], Score],
    model: str,
    profile: Profile,
    send: Callable[[str], None],
    now: datetime,
) -> None:
    failed: list[str] = []
    for source in sources:
        try:
            postings = source.fetch()
        except SourceError as exc:
            log.warning("source %s failed: %s", source.name, exc)
            failed.append(source.name)
            continue
        log.info("source %s: %d postings", source.name, len(postings))
        for p in postings:
            store.upsert_posting(p, now)
            result = apply_rules(p, profile, source.allow_non_us, list(source.title_include))
            store.record_rule(p.job_id, result, now)

    since = now - timedelta(days=FRESH_DAYS)
    for p in store.jobs_to_score(since):
        try:
            result = score(p)
        except ScoreError as exc:
            log.warning("scoring %s failed: %s", p.job_id, exc)
            store.record_score_failure(p.job_id, p.content_hash, now)
            continue
        store.save_score(p.job_id, p.content_hash, result, model, now)

    today = now.astimezone(LISBON).date()
    rows = store.digest_candidates(MIN_FIT, since, today, DIGEST_SIZE)
    body = format_digest(
        rows,
        below=store.count_below(MIN_FIT, store.last_digest_at() or since),
        failed_scores=store.count_score_failed(since),
        failed_sources=failed,
        min_fit=MIN_FIT,
    )
    digest_id = store.create_digest(body, [r.job_id for r in rows], now)
    try:
        send(body)
    except TelegramError as exc:
        log.warning("digest not sent, hourly run will retry: %s", exc)
    else:
        store.mark_digest_sent(digest_id, now)
    send_alerts(store, send, now)


def build_sources(client: httpx.Client, settings: Settings, watchlist: Watchlist) -> list[Source]:
    sources = [
        Source(
            f"{c.name} ({c.ats})",
            partial(fetch_company, client, c),
            c.allow_non_us,
            tuple(c.title_include),
        )
        for c in watchlist.company
    ]
    if settings.handshake_enabled:
        sources.append(Source("Handshake", partial(fetch_handshake, client, settings)))
    return sources


def main() -> int:
    logging.basicConfig(filename="jobscout.log", level=logging.INFO, format=LOG_FORMAT)
    try:
        with file_lock():
            settings = Settings()
            watchlist = load_watchlist(settings.watchlist_path)
            resume = settings.resume_path.read_text(encoding="utf-8")
            scorer = ClaudeScorer(
                make_client(settings.anthropic_api_key, settings.anthropic_workspace_id),
                settings.anthropic_model,
            )
            store = Store.open(settings.db_path)
            send = partial(send_message, settings.telegram_bot_token, settings.telegram_chat_id)
            with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
                run_weekly(
                    store,
                    build_sources(client, settings, watchlist),
                    lambda p: scorer.score(p, watchlist.profile, resume),
                    settings.anthropic_model,
                    watchlist.profile,
                    send,
                    datetime.now(UTC),
                )
    except LockBusy:
        log.info("another run holds the lock; skipping")
        return 0
    except Exception:
        log.exception("weekly run failed")
        return 1
    log.info("weekly run done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
