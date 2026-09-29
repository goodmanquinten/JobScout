from datetime import date, timedelta

from helpers import NOW, TODAY, add_scored, make_posting, num_of

from jobscout.models import RuleResult

SINCE = NOW - timedelta(days=8)


def test_upsert_reports_new_same_changed(store):
    p = make_posting()
    assert store.upsert_posting(p, NOW) == "new"
    assert store.upsert_posting(p, NOW + timedelta(hours=1)) == "same"
    assert store.upsert_posting(make_posting(description="edited"), NOW) == "changed"
    last_seen = store.conn.execute("SELECT last_seen FROM jobs").fetchone()[0]
    assert last_seen == NOW.isoformat()


def test_jobs_get_increasing_numbers(store):
    store.upsert_posting(make_posting(source_id="a"), NOW)
    store.upsert_posting(make_posting(source_id="b"), NOW)
    nums = [r[0] for r in store.conn.execute("SELECT num FROM jobs ORDER BY num")]
    assert nums == [1, 2]


def test_jobs_to_score_only_kept_unscored_and_fresh(store):
    kept = make_posting(source_id="kept")
    dropped = make_posting(source_id="dropped")
    stale = make_posting(source_id="stale")
    for p in (kept, dropped):
        store.upsert_posting(p, NOW)
    store.upsert_posting(stale, NOW - timedelta(days=30))
    store.record_rule(kept.job_id, RuleResult(keep=True), NOW)
    store.record_rule(dropped.job_id, RuleResult(keep=False, reason="x"), NOW)
    store.record_rule(stale.job_id, RuleResult(keep=True), NOW)
    assert [p.source_id for p in store.jobs_to_score(SINCE)] == ["kept"]


def test_scored_job_not_rescored_until_it_changes(store):
    p = add_scored(store, NOW, fit=7)
    assert store.jobs_to_score(SINCE) == []
    store.upsert_posting(make_posting(description="new text"), NOW)
    assert [q.source_id for q in store.jobs_to_score(SINCE)] == [p.source_id]


def test_failures_retry_three_times_then_stop(store):
    p = make_posting()
    store.upsert_posting(p, NOW)
    store.record_rule(p.job_id, RuleResult(keep=True), NOW)
    for _ in range(2):
        store.record_score_failure(p.job_id, p.content_hash, NOW)
        assert len(store.jobs_to_score(SINCE, max_attempts=3)) == 1
    store.record_score_failure(p.job_id, p.content_hash, NOW)
    assert store.jobs_to_score(SINCE, max_attempts=3) == []
    assert store.count_score_failed(SINCE, max_attempts=3) == 1


def test_count_below(store):
    add_scored(store, NOW, fit=3, source_id="a")
    add_scored(store, NOW, fit=5, source_id="b")
    add_scored(store, NOW, fit=8, source_id="c")
    assert store.count_below(6, NOW - timedelta(seconds=1)) == 2
    assert store.count_below(6, NOW) == 0  # strictly after the cut-off


def test_digest_candidates_order_and_exclusions(store):
    low = add_scored(store, NOW, fit=5, source_id="low")
    late = add_scored(store, NOW, fit=8, source_id="late", deadline=date(2026, 11, 1))
    soon = add_scored(store, NOW, fit=8, source_id="soon", deadline=date(2026, 10, 5))
    nodl = add_scored(store, NOW, fit=8, source_id="nodl")
    top = add_scored(store, NOW, fit=9, source_id="top")
    past = add_scored(store, NOW, fit=9, source_id="past", deadline=date(2026, 9, 1))
    skipped = add_scored(store, NOW, fit=9, source_id="skipped")
    store.set_status(num_of(store, skipped), "skipped", NOW)

    rows = store.digest_candidates(6, SINCE, TODAY, limit=10)
    assert [r.job_id for r in rows] == [top.job_id, soon.job_id, late.job_id, nodl.job_id]
    assert low.job_id not in {r.job_id for r in rows}
    assert past.job_id not in {r.job_id for r in rows}
    assert rows[0].num == num_of(store, top)

    assert len(store.digest_candidates(6, SINCE, TODAY, limit=2)) == 2


def test_jobs_already_in_a_digest_are_not_repeated(store):
    p = add_scored(store, NOW, fit=9)
    assert store.last_digest_at() is None
    digest_id = store.create_digest("body", [p.job_id], NOW)
    assert store.last_digest_at() == NOW
    assert store.digest_candidates(6, SINCE, TODAY, limit=10) == []
    assert store.unsent_digests() == [(digest_id, "body")]
    store.mark_digest_sent(digest_id, NOW)
    assert store.unsent_digests() == []


def test_set_status_and_list(store):
    a = add_scored(store, NOW, fit=9, source_id="a", deadline=date(2026, 10, 10))
    b = add_scored(store, NOW, fit=7, source_id="b")
    assert store.set_status(num_of(store, a), "saved", NOW) == (
        "ICONIQ",
        "Analyst, Financial Advisory",
    )
    store.set_status(num_of(store, b), "applied", NOW)
    assert store.set_status(999, "saved", NOW) is None
    assert store.state_of(a.job_id) == "saved"
    assert store.state_of("missing") == "new"
    listed = store.saved_and_applied()
    assert [(row.job_id, state) for row, state in listed] == [
        (a.job_id, "saved"),
        (b.job_id, "applied"),
    ]


def test_urgent_candidates_window_and_once(store):
    inside = add_scored(store, NOW, fit=8, source_id="in", deadline=date(2026, 10, 3))
    add_scored(store, NOW, fit=8, source_id="far", deadline=date(2026, 10, 20))
    add_scored(store, NOW, fit=7, source_id="weak", deadline=date(2026, 9, 30))
    applied = add_scored(store, NOW, fit=9, source_id="done", deadline=date(2026, 9, 30))
    store.set_status(num_of(store, applied), "applied", NOW)

    rows = store.urgent_candidates(TODAY, min_fit=8, within_days=7)
    assert [r.job_id for r in rows] == [inside.job_id]
    store.record_alert(inside.job_id, "urgent", NOW)
    store.record_alert(inside.job_id, "urgent", NOW)  # idempotent
    assert store.urgent_candidates(TODAY, min_fit=8, within_days=7) == []


def test_reminder_candidates_only_saved(store):
    saved = add_scored(store, NOW, fit=6, source_id="s", deadline=date(2026, 9, 30))
    add_scored(store, NOW, fit=6, source_id="n", deadline=date(2026, 9, 30))
    store.set_status(num_of(store, saved), "saved", NOW)
    rows = store.reminder_candidates(TODAY, days_before=3)
    assert [r.job_id for r in rows] == [saved.job_id]
    store.record_alert(saved.job_id, "reminder", NOW)
    assert store.reminder_candidates(TODAY, days_before=3) == []


def test_telegram_offset(store):
    assert store.telegram_offset() is None
    store.set_telegram_offset(41)
    store.set_telegram_offset(42)
    assert store.telegram_offset() == 42


def test_top_scored_includes_low_and_shown_but_not_skipped_or_closed(store):
    low = add_scored(store, NOW, fit=2, source_id="low")
    shown = add_scored(store, NOW, fit=9, source_id="shown")
    store.create_digest("d", [shown.job_id], NOW)
    skipped = add_scored(store, NOW, fit=8, source_id="skipped")
    store.set_status(num_of(store, skipped), "skipped", NOW)
    add_scored(store, NOW, fit=7, source_id="closed", deadline=date(2026, 9, 1))
    stale = make_posting(source_id="stale")
    add_scored(store, NOW - timedelta(days=30), fit=10, source_id="stale")
    rows = store.top_scored(SINCE, TODAY, limit=20)
    assert [r.job_id for r in rows] == [shown.job_id, low.job_id]
    assert stale.job_id not in {r.job_id for r in rows}
    assert len(store.top_scored(SINCE, TODAY, limit=1)) == 1


def test_normalize_company():
    from jobscout.store import company_matches, normalize_company

    assert normalize_company("ICONIQ Capital, LLC") == "iconiq capital"
    assert company_matches("ICONIQ Capital", "iconiq")
    assert company_matches("ICONIQ", "iconiq capital")
    assert not company_matches("Iconiqa Partners", "iconiq")


def test_blocked_company_disappears_everywhere(store):
    keep = add_scored(store, NOW, fit=7, source_id="keep", company="Bloomberg")
    add_scored(store, NOW, fit=9, source_id="a", company="ICONIQ", deadline=date(2026, 10, 1))
    saved = add_scored(
        store, NOW, fit=6, source_id="b", company="ICONIQ Capital", deadline=date(2026, 9, 30)
    )
    store.set_status(num_of(store, saved), "saved", NOW)
    unscored = make_posting(source_id="c", company="ICONIQ")
    store.upsert_posting(unscored, NOW)
    store.record_rule(unscored.job_id, RuleResult(keep=True), NOW)

    assert store.block_company("ICONIQ", NOW) is True
    assert store.block_company("iconiq", NOW) is False  # already blocked

    assert [r.job_id for r in store.digest_candidates(6, SINCE, TODAY, 10)] == [keep.job_id]
    assert [r.job_id for r in store.top_scored(SINCE, TODAY, 10)] == [keep.job_id]
    assert store.urgent_candidates(TODAY, 8, 7) == []
    assert store.reminder_candidates(TODAY, 3) == []
    assert store.jobs_to_score(SINCE) == []
    assert store.blocked_companies() == ["iconiq"]


def test_blocks_survive_reopening(tmp_path):
    from jobscout.store import Store

    path = tmp_path / "db.sqlite"
    Store.open(path).block_company("ICONIQ", NOW)
    assert Store.open(path).blocked_companies() == ["iconiq"]
