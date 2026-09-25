import base64
from pathlib import Path

import httpx
import pytest

from jobscout.sources.ats import SourceError
from jobscout.sources.handshake_mail import (
    GMAIL_API,
    extract_html,
    fetch_alert_postings,
    parse_alert,
)

FIXTURES = Path(__file__).parent / "fixtures"


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_parse_alert():
    html = (FIXTURES / "handshake_alert.html").read_text(encoding="utf-8")
    postings = parse_alert(html)
    assert [(p.source_id, p.title, p.company, p.location) for p in postings] == [
        ("10861709", "Fund Placement Analyst", "M2O Private Fund Advisors", "White Plains, NY"),
        ("10999999", "Analytics & Sales Program", "Bloomberg", "New York, NY"),
    ]
    assert postings[0].source == "handshake"
    assert postings[0].url == "https://app.joinhandshake.com/jobs/10861709"


def test_parse_real_alert_if_captured():
    real = FIXTURES / "handshake_real.html"
    if not real.exists():
        pytest.skip("capture one with: uv run python -m jobscout.sources.handshake_mail dump")
    postings = parse_alert(real.read_text(encoding="utf-8"))
    assert postings, "parser found no jobs in the real Handshake email"
    assert all(p.title and p.company != "Unknown" for p in postings)


def test_extract_html_walks_multipart():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("plain")}},
            {"mimeType": "text/html", "body": {"data": b64("<p>hi</p>")}},
        ],
    }
    assert extract_html(payload) == "<p>hi</p>"
    assert extract_html({"mimeType": "text/plain", "body": {"data": b64("x")}}) == ""


def test_fetch_alert_postings(httpx_mock):
    html = (FIXTURES / "handshake_alert.html").read_text(encoding="utf-8")
    httpx_mock.add_response(
        url=httpx.URL(
            f"{GMAIL_API}/messages",
            params={"q": "from:joinhandshake.com newer_than:8d", "maxResults": 25},
        ),
        json={"messages": [{"id": "m1"}, {"id": "m2"}]},
    )
    for mid in ("m1", "m2"):
        httpx_mock.add_response(
            url=httpx.URL(f"{GMAIL_API}/messages/{mid}", params={"format": "full"}),
            json={"payload": {"mimeType": "text/html", "body": {"data": b64(html)}}},
        )
    with httpx.Client() as client:
        postings = fetch_alert_postings(client, "token", "joinhandshake.com")
    assert len(postings) == 2  # the same jobs in both emails are deduplicated
    request = httpx_mock.get_requests()[0]
    assert request.headers["Authorization"] == "Bearer token"


def test_fetch_alert_postings_http_error(httpx_mock):
    httpx_mock.add_response(status_code=401)
    with httpx.Client() as client, pytest.raises(SourceError, match="Gmail"):
        fetch_alert_postings(client, "expired", "joinhandshake.com")
