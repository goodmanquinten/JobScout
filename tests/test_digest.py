from datetime import date

from jobscout.digest import (
    format_digest,
    format_list,
    format_reminder,
    format_row,
    format_urgent,
)
from jobscout.models import DigestRow

ROW = DigestRow(
    num=12,
    job_id="x",
    company="ICONIQ",
    title="Analyst, Financial Advisory",
    url="https://example.com/a?b=1&c=2",
    fit=9,
    reason="Summer 2027 start; options trading in role",
    deadline=date(2026, 10, 30),
)


def test_format_row():
    assert format_row(ROW) == (
        "#12 <b>ICONIQ</b>, Analyst, Financial Advisory · 9/10 · closes Oct 30\n"
        "Summer 2027 start; options trading in role · "
        '<a href="https://example.com/a?b=1&amp;c=2">link</a>'
    )


def test_format_row_escapes_and_omits_missing_deadline():
    row = ROW.model_copy(update={"company": "A&B <Capital>", "deadline": None})
    text = format_row(row)
    assert "<b>A&amp;B &lt;Capital&gt;</b>" in text
    assert "closes" not in text


def test_digest_with_footer():
    text = format_digest(
        [ROW], below=23, failed_scores=2, failed_sources=["Harrison Street (lever)"], min_fit=6
    )
    lines = text.split("\n")
    assert lines[0] == "<b>Jobs this week</b>"
    assert "#12 <b>ICONIQ</b>" in text
    assert "23 more below 6 · 2 couldn't be scored · failed: Harrison Street (lever)" in lines
    assert lines[-1] == "Reply /save N, /applied N or /skip N"


def test_empty_digest():
    text = format_digest([], below=0, failed_scores=0, failed_sources=[], min_fit=6)
    assert text == "<b>Jobs this week</b>\n\nNo new matches this week."


def test_urgent_and_reminder():
    assert format_urgent(ROW).startswith("<b>Closes soon</b>\n#12 ")
    assert format_reminder(ROW, date(2026, 10, 27)).startswith(
        "<b>Saved job closes in 3 days</b>\n#12 "
    )
    assert format_reminder(ROW, date(2026, 10, 29)).startswith("<b>Saved job closes tomorrow</b>")
    assert format_reminder(ROW, date(2026, 10, 30)).startswith("<b>Saved job closes today</b>")


def test_format_list():
    other = ROW.model_copy(
        update={"num": 3, "company": "HSBC", "title": "S&T Graduate", "deadline": None}
    )
    text = format_list([(ROW, "saved"), (other, "applied")])
    assert text == (
        "<b>Saved</b>\n#12 ICONIQ, Analyst, Financial Advisory · closes Oct 30\n\n"
        "<b>Applied</b>\n#3 HSBC, S&amp;T Graduate"
    )
    assert format_list([]) == "Nothing saved or applied yet."
