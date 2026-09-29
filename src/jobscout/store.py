"""SQLite persistence for JobScout.

Timestamps are ISO-8601 strings of UTC datetimes and deadlines are ISO dates, so
plain string comparison orders both correctly. Callers must pass UTC `now` values.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from jobscout.models import DigestRow, JobState, Posting, RuleResult, Score

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    num INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    posted_at TEXT,
    deadline TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_results (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    keep INTEGER NOT NULL,
    reason TEXT,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    content_hash TEXT NOT NULL,
    fit INTEGER,
    timing TEXT,
    deadline TEXT,
    reason TEXT,
    model TEXT,
    scored_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS status (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE (job_id, kind)
);
CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS digest_items (
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    position INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    PRIMARY KEY (digest_id, position)
);
CREATE TABLE IF NOT EXISTS blocked_companies (
    company TEXT PRIMARY KEY,  -- normalized name, see normalize_company
    blocked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_offset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    update_id INTEGER NOT NULL
);
"""

MAX_ATTEMPTS = 3
FRESH_DAYS = 8  # a job not seen in any source for this long counts as closed
_DEADLINE = "COALESCE(j.deadline, s.deadline)"
_ROWS = f"""
SELECT j.num, j.job_id, j.company, j.title, j.url, s.fit, s.reason,
       {_DEADLINE} AS deadline, COALESCE(st.state, 'new') AS state
FROM jobs j
JOIN scores s ON s.job_id = j.job_id
LEFT JOIN status st ON st.job_id = j.job_id
"""


_SUFFIXES = {"inc", "llc", "lp", "llp", "ltd", "corp", "corporation", "co", "company"}


def normalize_company(name: str) -> str:
    """Lowercase, no punctuation or legal suffix: 'ICONIQ Capital, LLC' -> 'iconiq capital'."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def company_matches(company: str, blocked: str) -> bool:
    """Same company when one normalized name equals, or is a word-prefix of, the other."""
    a, b = normalize_company(company), normalize_company(blocked)
    if not a or not b:
        return False
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def _posting(r: sqlite3.Row) -> Posting:
    return Posting(
        source=r["source"],
        source_id=r["source_id"],
        url=r["url"],
        company=r["company"],
        title=r["title"],
        location=r["location"],
        description=r["description"],
        posted_at=datetime.fromisoformat(r["posted_at"]) if r["posted_at"] else None,
        deadline=date.fromisoformat(r["deadline"]) if r["deadline"] else None,
    )


def _row(r: sqlite3.Row) -> DigestRow:
    return DigestRow(
        num=r["num"],
        job_id=r["job_id"],
        company=r["company"],
        title=r["title"],
        url=r["url"],
        fit=r["fit"],
        reason=r["reason"] or "",
        deadline=date.fromisoformat(r["deadline"]) if r["deadline"] else None,
    )


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        self.conn = conn
        self._blocked = [
            r["company"] for r in conn.execute("SELECT company FROM blocked_companies")
        ]
        conn.create_function("is_blocked", 1, self._is_blocked)

    def _is_blocked(self, company: str) -> int:
        return int(any(company_matches(company, b) for b in self._blocked))

    @classmethod
    def open(cls, path: Path | str) -> Store:
        return cls(sqlite3.connect(path))

    # --- postings, rules, scores -------------------------------------------------

    def upsert_posting(self, p: Posting, now: datetime) -> Literal["new", "changed", "same"]:
        ts = now.isoformat()
        old = self.conn.execute(
            "SELECT content_hash FROM jobs WHERE job_id = ?", (p.job_id,)
        ).fetchone()
        values = (
            p.url,
            p.company,
            p.title,
            p.location,
            p.description,
            p.content_hash,
            _iso(p.posted_at),
            _iso(p.deadline),
        )
        with self.conn:
            if old is None:
                self.conn.execute(
                    "INSERT INTO jobs (job_id, source, source_id, url, company, title, location,"
                    " description, content_hash, posted_at, deadline, first_seen, last_seen)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (p.job_id, p.source, p.source_id, *values, ts, ts),
                )
                return "new"
            self.conn.execute(
                "UPDATE jobs SET url = ?, company = ?, title = ?, location = ?, description = ?,"
                " content_hash = ?, posted_at = ?, deadline = ?, last_seen = ? WHERE job_id = ?",
                (*values, ts, p.job_id),
            )
        return "same" if old["content_hash"] == p.content_hash else "changed"

    def record_rule(self, job_id: str, result: RuleResult, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO rule_results (job_id, keep, reason, checked_at)"
                " VALUES (?, ?, ?, ?)",
                (job_id, int(result.keep), result.reason, now.isoformat()),
            )

    def jobs_to_score(self, since: datetime, max_attempts: int = MAX_ATTEMPTS) -> list[Posting]:
        """Kept jobs seen since `since` with no score for their current text."""
        rows = self.conn.execute(
            "SELECT j.* FROM jobs j"
            " JOIN rule_results r ON r.job_id = j.job_id AND r.keep = 1"
            " LEFT JOIN scores s ON s.job_id = j.job_id"
            " WHERE j.last_seen >= ? AND NOT is_blocked(j.company)"
            " AND (s.job_id IS NULL OR s.content_hash != j.content_hash"
            "      OR (s.fit IS NULL AND s.attempts < ?))"
            " ORDER BY j.num",
            (since.isoformat(), max_attempts),
        ).fetchall()
        return [_posting(r) for r in rows]

    def save_score(
        self, job_id: str, content_hash: str, score: Score, model: str, now: datetime
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO scores (job_id, content_hash, fit, timing, deadline,"
                " reason, model, scored_at, attempts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    job_id,
                    content_hash,
                    score.fit,
                    score.timing,
                    _iso(score.deadline),
                    score.reason,
                    model,
                    now.isoformat(),
                ),
            )

    def record_score_failure(self, job_id: str, content_hash: str, now: datetime) -> None:
        """Count a failed attempt; attempts restart at 1 when the posting text changed."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO scores (job_id, content_hash, fit, scored_at, attempts)"
                " VALUES (?, ?, NULL, ?, 1)"
                " ON CONFLICT(job_id) DO UPDATE SET"
                "  attempts = CASE WHEN scores.content_hash = excluded.content_hash"
                "                   AND scores.fit IS NULL"
                "              THEN scores.attempts + 1 ELSE 1 END,"
                "  content_hash = excluded.content_hash, fit = NULL, timing = NULL,"
                "  deadline = NULL, reason = NULL, scored_at = excluded.scored_at",
                (job_id, content_hash, now.isoformat()),
            )

    def count_score_failed(self, since: datetime, max_attempts: int = MAX_ATTEMPTS) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM scores s JOIN jobs j ON j.job_id = s.job_id"
            " WHERE s.fit IS NULL AND s.attempts >= ? AND j.last_seen >= ?",
            (max_attempts, since.isoformat()),
        ).fetchone()[0]

    def count_below(self, min_fit: int, scored_after: datetime) -> int:
        """Jobs scored after `scored_after` (normally the last digest) under the cut-off."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM scores WHERE fit IS NOT NULL AND fit < ? AND scored_at > ?",
            (min_fit, scored_after.isoformat()),
        ).fetchone()[0]

    # --- digests -------------------------------------------------------------------

    def digest_candidates(
        self, min_fit: int, since: datetime, today: date, limit: int
    ) -> list[DigestRow]:
        """Best new, still-open jobs never shown in a digest."""
        rows = self.conn.execute(
            _ROWS + " WHERE s.fit >= ? AND j.last_seen >= ? AND NOT is_blocked(j.company)"
            " AND COALESCE(st.state, 'new') = 'new'"
            f" AND ({_DEADLINE} IS NULL OR {_DEADLINE} >= ?)"
            " AND j.job_id NOT IN (SELECT job_id FROM digest_items)"
            f" ORDER BY s.fit DESC, {_DEADLINE} IS NULL, {_DEADLINE}, j.num LIMIT ?",
            (min_fit, since.isoformat(), today.isoformat(), limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def top_scored(self, since: datetime, today: date, limit: int) -> list[DigestRow]:
        """All scored, still-open jobs (any fit, shown before or not), best first."""
        rows = self.conn.execute(
            _ROWS + " WHERE s.fit IS NOT NULL AND j.last_seen >= ? AND NOT is_blocked(j.company)"
            " AND COALESCE(st.state, 'new') NOT IN ('skipped', 'rejected')"
            f" AND ({_DEADLINE} IS NULL OR {_DEADLINE} >= ?)"
            f" ORDER BY s.fit DESC, {_DEADLINE} IS NULL, {_DEADLINE}, j.num LIMIT ?",
            (since.isoformat(), today.isoformat(), limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def create_digest(self, body: str, job_ids: list[str], now: datetime) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO digests (created_at, body) VALUES (?, ?)", (now.isoformat(), body)
            )
            digest_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO digest_items (digest_id, position, job_id) VALUES (?, ?, ?)",
                [(digest_id, i, job_id) for i, job_id in enumerate(job_ids, start=1)],
            )
        return digest_id

    def last_digest_at(self) -> datetime | None:
        row = self.conn.execute("SELECT MAX(created_at) AS at FROM digests").fetchone()
        return datetime.fromisoformat(row["at"]) if row["at"] else None

    def mark_digest_sent(self, digest_id: int, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE digests SET sent_at = ? WHERE id = ?", (now.isoformat(), digest_id)
            )

    def unsent_digests(self) -> list[tuple[int, str]]:
        rows = self.conn.execute(
            "SELECT id, body FROM digests WHERE sent_at IS NULL ORDER BY id"
        ).fetchall()
        return [(r["id"], r["body"]) for r in rows]

    # --- status --------------------------------------------------------------------

    def set_status(self, num: int, state: JobState, now: datetime) -> tuple[str, str] | None:
        """Set a job's state by its #num. Returns (company, title), or None if unknown."""
        job = self.conn.execute(
            "SELECT job_id, company, title FROM jobs WHERE num = ?", (num,)
        ).fetchone()
        if job is None:
            return None
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO status (job_id, state, updated_at) VALUES (?, ?, ?)",
                (job["job_id"], state, now.isoformat()),
            )
        return job["company"], job["title"]

    def state_of(self, job_id: str) -> JobState:
        row = self.conn.execute("SELECT state FROM status WHERE job_id = ?", (job_id,)).fetchone()
        return row["state"] if row else "new"

    def saved_and_applied(self) -> list[tuple[DigestRow, str]]:
        rows = self.conn.execute(
            _ROWS + " WHERE st.state IN ('saved', 'applied')"
            f" ORDER BY st.state DESC, {_DEADLINE} IS NULL, {_DEADLINE}, j.num"
        ).fetchall()
        return [(_row(r), r["state"]) for r in rows]

    # --- blocked companies -----------------------------------------------------------

    def block_company(self, company: str, now: datetime) -> bool:
        """Never recommend this company again. Returns False if it was already blocked."""
        name = normalize_company(company)
        if not name or any(company_matches(name, b) for b in self._blocked):
            return False
        with self.conn:
            self.conn.execute(
                "INSERT INTO blocked_companies (company, blocked_at) VALUES (?, ?)",
                (name, now.isoformat()),
            )
        self._blocked.append(name)
        return True

    def blocked_companies(self) -> list[str]:
        return sorted(self._blocked)

    # --- alerts --------------------------------------------------------------------

    def urgent_candidates(self, today: date, min_fit: int, within_days: int) -> list[DigestRow]:
        until = today + timedelta(days=within_days)
        rows = self.conn.execute(
            _ROWS
            + f" WHERE s.fit >= ? AND {_DEADLINE} BETWEEN ? AND ? AND NOT is_blocked(j.company)"
            " AND COALESCE(st.state, 'new') IN ('new', 'saved')"
            " AND NOT EXISTS (SELECT 1 FROM alerts a"
            "                 WHERE a.job_id = j.job_id AND a.kind = 'urgent')"
            f" ORDER BY {_DEADLINE}, j.num",
            (min_fit, today.isoformat(), until.isoformat()),
        ).fetchall()
        return [_row(r) for r in rows]

    def reminder_candidates(self, today: date, days_before: int) -> list[DigestRow]:
        until = today + timedelta(days=days_before)
        rows = self.conn.execute(
            _ROWS + f" WHERE st.state = 'saved' AND {_DEADLINE} BETWEEN ? AND ?"
            " AND NOT is_blocked(j.company)"
            " AND NOT EXISTS (SELECT 1 FROM alerts a"
            "                 WHERE a.job_id = j.job_id AND a.kind = 'reminder')"
            f" ORDER BY {_DEADLINE}, j.num",
            (today.isoformat(), until.isoformat()),
        ).fetchall()
        return [_row(r) for r in rows]

    def record_alert(self, job_id: str, kind: str, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO alerts (job_id, kind, sent_at) VALUES (?, ?, ?)",
                (job_id, kind, now.isoformat()),
            )

    # --- telegram ------------------------------------------------------------------

    def telegram_offset(self) -> int | None:
        row = self.conn.execute("SELECT update_id FROM telegram_offset WHERE id = 1").fetchone()
        return row["update_id"] if row else None

    def set_telegram_offset(self, update_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO telegram_offset (id, update_id) VALUES (1, ?)"
                " ON CONFLICT(id) DO UPDATE SET update_id = excluded.update_id",
                (update_id,),
            )
