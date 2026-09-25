from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobscout.config import Settings, load_watchlist

REPO = Path(__file__).resolve().parents[1]


def test_load_watchlist(tmp_path):
    path = tmp_path / "w.toml"
    path.write_text(
        """
[profile]
available_from = 2027-06-01
targets = ["investment analyst"]

[[company]]
name = "ICONIQ"
ats = "greenhouse"
token = "iconiq"

[[company]]
name = "Some UK Fund"
ats = "lever"
token = "ukfund"
allow_non_us = true
""",
        encoding="utf-8",
    )
    wl = load_watchlist(path)
    assert wl.profile.available_from == date(2027, 6, 1)
    assert wl.profile.max_years_required == 2
    assert [c.token for c in wl.company] == ["iconiq", "ukfund"]
    assert wl.company[1].allow_non_us is True


def test_unknown_ats_rejected(tmp_path):
    path = tmp_path / "w.toml"
    path.write_text(
        "[profile]\navailable_from = 2027-06-01\n\n"
        '[[company]]\nname = "X"\nats = "workday"\ntoken = "x"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_watchlist(path)


def test_repo_watchlist_is_valid():
    wl = load_watchlist(REPO / "watchlist.toml")
    assert wl.profile.available_from == date(2027, 6, 1)
    assert wl.company


def test_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    s = Settings()
    assert s.anthropic_model == "claude-sonnet-5"
    assert s.handshake_enabled is True
    assert s.db_path == Path("jobscout.db")


def test_title_include_defaults_empty(tmp_path):
    path = tmp_path / "w.toml"
    path.write_text(
        "[profile]\navailable_from = 2027-06-01\n\n"
        '[[company]]\nname = "A"\nats = "ashby"\ntoken = "a"\ntitle_include = ["financ"]\n\n'
        '[[company]]\nname = "B"\nats = "lever"\ntoken = "b"\n',
        encoding="utf-8",
    )
    wl = load_watchlist(path)
    assert wl.company[0].title_include == ["financ"]
    assert wl.company[1].title_include == []
