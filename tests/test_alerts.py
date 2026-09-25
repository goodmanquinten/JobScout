from datetime import UTC, date, datetime

import pytest
from helpers import NOW, add_scored, num_of

from jobscout.alerts import is_quiet, send_alerts
from jobscout.telegram import TelegramError


@pytest.mark.parametrize(
    ("utc_hour", "utc_minute", "quiet"),
    [(22, 30, True), (6, 59, True), (7, 0, False), (21, 59, False)],  # Lisbon = UTC+1 in Sept
)
def test_is_quiet(utc_hour, utc_minute, quiet):
    assert is_quiet(datetime(2026, 9, 27, utc_hour, utc_minute, tzinfo=UTC)) is quiet


def test_urgent_sent_once(store):
    add_scored(store, NOW, fit=8, deadline=date(2026, 10, 2))
    sent = []
    assert send_alerts(store, sent.append, NOW) == 1
    assert sent[0].startswith("<b>Closes soon</b>")
    assert send_alerts(store, sent.append, NOW) == 0


def test_nothing_during_quiet_hours(store):
    add_scored(store, NOW, fit=8, deadline=date(2026, 10, 2))
    sent = []
    assert send_alerts(store, sent.append, datetime(2026, 9, 27, 23, 0, tzinfo=UTC)) == 0
    assert sent == []
    assert send_alerts(store, sent.append, NOW) == 1  # still pending, sent after quiet hours


def test_reminder_for_saved_job(store):
    p = add_scored(store, NOW, fit=6, deadline=date(2026, 9, 30))
    store.set_status(num_of(store, p), "saved", NOW)
    sent = []
    send_alerts(store, sent.append, NOW)
    assert len(sent) == 1
    assert "Saved job closes in 3 days" in sent[0]


def test_telegram_failure_leaves_alert_pending(store):
    add_scored(store, NOW, fit=9, deadline=date(2026, 10, 1))

    def broken(_text):
        raise TelegramError("down")

    assert send_alerts(store, broken, NOW) == 0
    sent = []
    assert send_alerts(store, sent.append, NOW) == 1
