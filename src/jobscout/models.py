"""Domain models shared across JobScout."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Timing = Literal["fits_june_2027", "unclear", "needs_start_now"]
JobState = Literal["new", "saved", "applied", "skipped"]


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Posting(BaseModel):
    """One job posting as read from a source."""

    source: str  # e.g. "greenhouse:iconiq", "lever:harrisonst", "handshake"
    source_id: str
    url: str
    company: str
    title: str
    location: str = ""
    description: str = ""
    posted_at: datetime | None = None
    deadline: date | None = None

    @property
    def job_id(self) -> str:
        """Stable identity: the same source + id is the same job."""
        return _short_hash(f"{self.source}:{self.source_id}")

    @property
    def content_hash(self) -> str:
        """Changes when the posting text changes, which triggers a rescore."""
        return _short_hash(f"{self.title}\n{self.description}")


class RuleResult(BaseModel):
    keep: bool
    reason: str | None = None


class Score(BaseModel):
    fit: int = Field(ge=1, le=10)
    timing: Timing
    deadline: date | None = None
    reason: str = Field(max_length=140)


class DigestRow(BaseModel):
    """A scored job as shown in a Telegram message."""

    num: int  # permanent #N the user types in commands
    job_id: str
    company: str
    title: str
    url: str
    fit: int
    reason: str
    deadline: date | None = None
