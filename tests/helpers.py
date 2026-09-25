"""Shared test helpers (importable because pytest adds tests/ to sys.path)."""

from __future__ import annotations

from datetime import UTC, date, datetime

# Sunday 2026-09-27 17:00 UTC == 18:00 in Lisbon (WEST, UTC+1): the weekly slot.
NOW = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
TODAY = date(2026, 9, 27)
