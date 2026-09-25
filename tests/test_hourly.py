from datetime import UTC, date, datetime

from helpers import NOW, add_scored, num_of

from jobscout.hourly import run_hourly
from jobscout.telegram import TelegramError

CHAT = "99"


def update(update_id, text, chat=CHAT):
    return {"update_id": update_id, "message": {"chat": {"id": int(chat)}, "text": text}}


def test_commands_from_owner_only(store):
    p = add_scored(store, NOW, fit=7)
    n = num_of(store, p)
    updates = [update(10, f"/applied {n}"), update(11, f"/skip {n}", chat="5"), update(12, "hi")]
    offsets, sent = [], []

    def fetch(offset):
        offsets.append(offset)
        return updates

    run_hourly(store, fetch, sent.append, CHAT, NOW)
    assert offsets == [None]
    assert store.state_of(p.job_id) == "applied"  # the other chat's /skip was ignored
    assert sent == [f"#{n} ICONIQ, Analyst, Financial Advisory: applied"]  # plain text ignored
    assert store.telegram_offset() == 13


def test_resends_unsent_digest_and_sends_alerts(store):
    store.create_digest("old digest", [], NOW)
    add_scored(store, NOW, fit=9, deadline=date(2026, 10, 1))
    sent = []
    run_hourly(store, lambda _o: [], sent.append, CHAT, NOW)
    assert sent[0] == "old digest"
    assert sent[1].startswith("<b>Closes soon</b>")
    assert store.unsent_digests() == []


def test_quiet_hours_still_answer_commands(store):
    night = datetime(2026, 9, 27, 23, 30, tzinfo=UTC)
    add_scored(store, NOW, fit=9, deadline=date(2026, 10, 1))
    sent = []
    run_hourly(store, lambda _o: [update(1, "/list")], sent.append, CHAT, night)
    assert sent == ["Nothing saved or applied yet."]


def test_telegram_down_is_not_fatal(store):
    def fetch(_offset):
        raise TelegramError("down")

    run_hourly(store, fetch, lambda _t: None, CHAT, NOW)  # no exception
