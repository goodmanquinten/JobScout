from datetime import date
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from helpers import make_posting

from jobscout.config import Profile
from jobscout.score import ClaudeScorer, ScoreError, ScoreOut, to_score

PROFILE = Profile(available_from=date(2027, 6, 1), targets=["investment analyst"])


class FakeMessages:
    def __init__(self, out=None, exc=None, stop_reason="end_turn"):
        self.out, self.exc, self.stop_reason = out, exc, stop_reason
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.out)


def scorer_with(messages):
    return ClaudeScorer(client=SimpleNamespace(messages=messages), model="test-model")


def out(**kw):
    fields = {"fit": 8, "timing": "fits_june_2027", "deadline": "2026-10-30", "reason": "Good fit"}
    fields.update(kw)
    return ScoreOut(**fields)


def test_to_score_parses_deadline():
    assert to_score(out()).deadline == date(2026, 10, 30)
    assert to_score(out(deadline="Oct 30")).deadline is None
    assert to_score(out(deadline=None)).deadline is None


def test_to_score_caps_needs_start_now():
    assert to_score(out(fit=9, timing="needs_start_now")).fit == 5
    assert to_score(out(fit=3, timing="needs_start_now")).fit == 3


def test_to_score_clamps_and_truncates():
    assert to_score(out(fit=14)).fit == 10
    assert to_score(out(fit=0)).fit == 1
    long = to_score(out(reason="word " * 60))
    assert len(long.reason) <= 140
    assert long.reason.endswith("…")


def test_score_sends_profile_resume_and_posting():
    messages = FakeMessages(out=out())
    score = scorer_with(messages).score(make_posting(title="Unique Title"), PROFILE, "RESUME TEXT")
    assert score.fit == 8
    call = messages.calls[0]
    assert call["model"] == "test-model"
    assert call["output_format"] is ScoreOut
    system_text = " ".join(block["text"] for block in call["system"])
    assert "RESUME TEXT" in system_text and "2027-06-01" in system_text
    assert "Unique Title" in call["messages"][0]["content"]


def test_api_error_raises_score_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    messages = FakeMessages(exc=anthropic.APIConnectionError(request=request))
    with pytest.raises(ScoreError):
        scorer_with(messages).score(make_posting(), PROFILE, "resume")


def test_bad_stop_reason_raises():
    with pytest.raises(ScoreError, match="max_tokens"):
        scorer_with(FakeMessages(out=out(), stop_reason="max_tokens")).score(
            make_posting(), PROFILE, "resume"
        )


def test_missing_output_raises():
    with pytest.raises(ScoreError):
        scorer_with(FakeMessages(out=None)).score(make_posting(), PROFILE, "resume")
