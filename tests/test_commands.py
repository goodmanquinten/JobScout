import pytest
from helpers import NOW, add_scored, num_of

from jobscout.commands import HELP, Command, handle, parse_command


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/save 12", Command("save", 12)),
        ("/applied #3", Command("applied", 3)),
        ("/SKIP 4", Command("skip", 4)),
        ("/list", Command("list", None)),
        ("/save@JobScoutBot 5", Command("save", 5)),
        ("/save", Command("save", None)),
        ("hello", None),
        ("/delete 3", None),
    ],
)
def test_parse_command(text, expected):
    assert parse_command(text) == expected


def test_handle_sets_status(store):
    p = add_scored(store, NOW, fit=9)
    n = num_of(store, p)
    reply = handle(store, f"/applied {n}", NOW)
    assert reply == f"#{n} ICONIQ, Analyst, Financial Advisory: applied"
    assert store.state_of(p.job_id) == "applied"


def test_handle_errors(store):
    assert handle(store, "/save 999", NOW) == "No job #999."
    assert handle(store, "/save", NOW) == "Usage: /save N"
    assert handle(store, "/delete 1", NOW) == HELP


def test_handle_list(store):
    p = add_scored(store, NOW, fit=9)
    handle(store, f"/save {num_of(store, p)}", NOW)
    assert handle(store, "/list", NOW).startswith("<b>Saved</b>")
