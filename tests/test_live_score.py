"""Real Claude call. Run with: uv run pytest -m live"""

import os
from datetime import date

import pytest
from helpers import make_posting

from jobscout.config import Profile, Settings
from jobscout.score import ClaudeScorer, make_client

pytestmark = pytest.mark.live


def test_live_score():
    settings = Settings()
    if not (settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("no ANTHROPIC_API_KEY")
    scorer = ClaudeScorer(
        make_client(settings.anthropic_api_key, settings.anthropic_workspace_id),
        settings.anthropic_model,
    )
    posting = make_posting(
        title="Analyst, Financial Advisory (Entry-Level)",
        description="For students graduating Spring 2027; start Summer 2027. "
        "Asset allocation, portfolio reports, equity and option trading.",
    )
    profile = Profile(available_from=date(2027, 6, 1), targets=["investment analyst"])
    score = scorer.score(posting, profile, "MSc Finance 2027. Python options analytics.")
    assert score.fit >= 6
    assert score.timing == "fits_june_2027"
