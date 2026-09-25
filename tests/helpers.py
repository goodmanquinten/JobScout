"""Shared test helpers (importable because pytest adds tests/ to sys.path)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from jobscout.models import Posting, RuleResult, Score

# Sunday 2026-09-27 17:00 UTC == 18:00 in Lisbon (WEST, UTC+1): the weekly slot.
NOW = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
TODAY = date(2026, 9, 27)


def make_posting(**overrides) -> Posting:
    fields = {
        "source": "greenhouse:iconiq",
        "source_id": "1",
        "url": "https://example.com/jobs/1",
        "company": "ICONIQ",
        "title": "Analyst, Financial Advisory",
        "location": "New York, NY",
        "description": "Entry-level role. 0-2 years of experience.",
    }
    fields.update(overrides)
    return Posting(**fields)


def add_scored(store, now, fit, deadline=None, timing="fits_june_2027", **posting_fields):
    """Insert a kept, scored posting and return it."""
    p = make_posting(**posting_fields)
    store.upsert_posting(p, now)
    store.record_rule(p.job_id, RuleResult(keep=True), now)
    score = Score(fit=fit, timing=timing, deadline=deadline, reason=f"fit {fit}")
    store.save_score(p.job_id, p.content_hash, score, "test-model", now)
    return p


def num_of(store, posting) -> int:
    row = store.conn.execute("SELECT num FROM jobs WHERE job_id = ?", (posting.job_id,)).fetchone()
    return row[0]
