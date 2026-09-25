"""Claude scores a posting against the candidate profile and resume."""

from __future__ import annotations

from datetime import date

import anthropic
import pydantic
from pydantic import BaseModel

from jobscout.config import Profile
from jobscout.models import Posting, Score, Timing

MAX_TOKENS = 2000
NOT_NOW_CAP = 5
MAX_REASON = 140

SYSTEM_PROMPT = """You screen job postings for one candidate and score how well each fits.

fit, 1 to 10:
- 9-10: entry-level role squarely in the candidate's targets; start date works; close skills match.
- 6-8: worth applying to; some gaps, or less central to the targets.
- 3-5: weak: wrong function, experience bar likely too high, or poor skills match.
- 1-2: clearly not a fit.

timing:
- "fits_june_2027": a 2027 program or summer-2027 start, or no start date stated and the role \
plausibly accepts someone available from the candidate's start date.
- "needs_start_now": clearly wants someone now or in 2026.
- "unclear": otherwise.

deadline: the application deadline as YYYY-MM-DD only if the posting states one, else null.
reason: one plain sentence under 140 characters giving the single most important reason for the \
score. No preamble."""


class ScoreOut(BaseModel):
    """What Claude returns; loosely typed so small slips don't fail validation."""

    fit: int
    timing: Timing
    deadline: str | None
    reason: str


class ScoreError(Exception):
    """Scoring failed; the posting stays unscored and is retried next run."""


def to_score(out: ScoreOut) -> Score:
    fit = max(1, min(10, out.fit))
    if out.timing == "needs_start_now":
        fit = min(fit, NOT_NOW_CAP)
    deadline = None
    if out.deadline:
        try:
            deadline = date.fromisoformat(out.deadline)
        except ValueError:
            deadline = None
    reason = " ".join(out.reason.split())
    if len(reason) > MAX_REASON:
        reason = reason[: MAX_REASON - 1].rstrip() + "…"
    return Score(fit=fit, timing=out.timing, deadline=deadline, reason=reason)


def candidate_block(profile: Profile, resume: str) -> str:
    return "\n".join(
        [
            "## Candidate",
            f"Available to start: {profile.available_from.isoformat()}",
            f"Work country: {profile.country}",
            f"Most years of experience they can claim: {profile.max_years_required}",
            f"Target roles: {'; '.join(profile.targets)}",
            profile.summary,
            "",
            "## Resume",
            resume.strip(),
        ]
    )


def posting_block(p: Posting) -> str:
    return "\n".join(
        [
            "## Posting",
            f"Company: {p.company}",
            f"Title: {p.title}",
            f"Location: {p.location or 'not stated'}",
            f"Deadline field: {p.deadline.isoformat() if p.deadline else 'none'}",
            "",
            p.description or "(No description available; judge from the title and company.)",
        ]
    )


def make_client(api_key: str, workspace_id: str = "") -> anthropic.Anthropic:
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")
    kwargs: dict[str, object] = {"api_key": api_key}
    if workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": workspace_id}
    return anthropic.Anthropic(**kwargs)


class ClaudeScorer:
    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        self._client = client
        self.model = model

    def score(self, posting: Posting, profile: Profile, resume: str) -> Score:
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT},
                    {
                        "type": "text",
                        "text": candidate_block(profile, resume),
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
                messages=[{"role": "user", "content": posting_block(posting)}],
                output_format=ScoreOut,
            )
        except (anthropic.APIError, pydantic.ValidationError) as exc:
            raise ScoreError(f"scoring call failed: {exc}") from exc
        if response.stop_reason != "end_turn":
            raise ScoreError(f"unexpected stop_reason={response.stop_reason}")
        if response.parsed_output is None:
            raise ScoreError("response had no parsed output")
        return to_score(response.parsed_output)
