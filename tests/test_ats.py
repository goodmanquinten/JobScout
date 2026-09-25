import json
from pathlib import Path

import httpx
import pytest

from jobscout.config import Company
from jobscout.sources.ats import SourceError, fetch_company, html_to_text

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_html_to_text_unescapes_and_keeps_line_breaks():
    raw = (
        "&lt;p&gt;One &amp;amp; two&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;A&lt;/li&gt;&lt;li&gt;B&lt;/li&gt;&lt;/ul&gt;"
    )
    assert html_to_text(raw) == "One & two\nA\nB"


def test_greenhouse(httpx_mock):
    httpx_mock.add_response(
        url="https://boards-api.greenhouse.io/v1/boards/iconiq/jobs?content=true",
        json=load("greenhouse.json"),
    )
    with httpx.Client() as client:
        [p] = fetch_company(client, Company(name="ICONIQ", ats="greenhouse", token="iconiq"))
    assert p.source == "greenhouse:iconiq"
    assert p.source_id == "8068011"
    assert p.company == "ICONIQ"
    assert p.location == "San Francisco, CA; New York, NY"
    assert "Spring 2027" in p.description
    assert "Equity & option trading" in p.description
    assert p.posted_at is not None


def test_lever(httpx_mock):
    httpx_mock.add_response(
        url="https://api.lever.co/v0/postings/harrisonst?mode=json", json=load("lever.json")
    )
    company = Company(name="Harrison Street", ats="lever", token="harrisonst")
    with httpx.Client() as client:
        [p] = fetch_company(client, company)
    assert p.title == "Summer 2027 Portfolio Management Analyst"
    assert p.location == "Chicago, IL"
    assert "early June 2027" in p.description
    assert "Update fund cash-flow models" in p.description
    assert "Excel and financial modeling" in p.description


def test_ashby_skips_unlisted(httpx_mock):
    httpx_mock.add_response(
        url="https://api.ashbyhq.com/posting-api/job-board/example", json=load("ashby.json")
    )
    with httpx.Client() as client:
        postings = fetch_company(client, Company(name="Example", ats="ashby", token="example"))
    assert [p.source_id for p in postings] == ["a1b2c3"]


def test_http_error_becomes_source_error(httpx_mock):
    httpx_mock.add_response(url="https://api.lever.co/v0/postings/nope?mode=json", status_code=404)
    with httpx.Client() as client, pytest.raises(SourceError):
        fetch_company(client, Company(name="Nope", ats="lever", token="nope"))


def test_malformed_payload_becomes_source_error(httpx_mock):
    httpx_mock.add_response(
        url="https://boards-api.greenhouse.io/v1/boards/bad/jobs?content=true",
        json={"jobs": [{"title": "missing id"}]},
    )
    with httpx.Client() as client, pytest.raises(SourceError):
        fetch_company(client, Company(name="Bad", ats="greenhouse", token="bad"))
