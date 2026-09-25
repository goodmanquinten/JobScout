from datetime import date, timedelta

from helpers import NOW, make_posting

from jobscout.config import Profile
from jobscout.models import Score
from jobscout.score import ScoreError
from jobscout.sources.ats import SourceError
from jobscout.telegram import TelegramError
from jobscout.weekly import Source, run_weekly

PROFILE = Profile(available_from=date(2027, 6, 1))

GOOD = make_posting(source_id="good", title="Investment Analyst")
OK = make_posting(source_id="ok", title="Financial Analyst I")
WEAK = make_posting(source_id="weak", title="Accounts Payable Clerk")
SENIOR = make_posting(source_id="senior", title="Senior Portfolio Manager")
BROKEN = make_posting(source_id="broken", title="Markets Analyst")

FITS = {"good": 9, "ok": 6, "weak": 3}


def fake_scorer(calls):
    def score(p):
        calls.append(p.source_id)
        if p.source_id == "broken":
            raise ScoreError("boom")
        return Score(fit=FITS[p.source_id], timing="fits_june_2027", reason="r")

    return score


def failing_source():
    raise SourceError("down")


def run(store, sent, calls, now=NOW, sources=None):
    sources = sources or [
        Source("Board", lambda: [GOOD, OK, WEAK, SENIOR, BROKEN]),
        Source("Harrison Street (lever)", failing_source),
    ]
    run_weekly(store, sources, fake_scorer(calls), "m", PROFILE, sent.append, now)


def test_weekly_digest(store):
    sent, calls = [], []
    run(store, sent, calls)
    assert sorted(calls) == ["broken", "good", "ok", "weak"]  # senior filtered by rules
    [digest] = sent
    assert digest.index("Investment Analyst") < digest.index("Financial Analyst I")
    assert "Accounts Payable" not in digest
    assert "couldn't be scored" not in digest  # broken has failed once; retried next week
    assert "1 more below 6" in digest
    assert "failed: Harrison Street (lever)" in digest
    assert store.unsent_digests() == []


def test_second_week_does_not_repeat_or_rescore(store):
    sent, calls = [], []
    run(store, sent, calls)
    sent2, calls2 = [], []
    run(store, sent2, calls2, now=NOW + timedelta(days=7))
    assert calls2 == ["broken"]  # only the failed one is retried
    assert "No new matches this week." in sent2[0]
    assert "more below" not in sent2[0]  # last week's weak job is not counted again


def test_unsent_digest_is_kept_when_telegram_fails(store):
    def broken_send(_text):
        raise TelegramError("down")

    run_weekly(
        store, [Source("Board", lambda: [GOOD])], fake_scorer([]), "m", PROFILE, broken_send, NOW
    )
    assert len(store.unsent_digests()) == 1


def test_source_title_include_is_applied(store):
    calls = []
    source = Source("Big Co", lambda: [GOOD, WEAK], title_include=("investment",))
    run_weekly(store, [source], fake_scorer(calls), "m", PROFILE, [].append, NOW)
    assert calls == ["good"]
