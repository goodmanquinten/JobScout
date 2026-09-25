"""Handshake job-alert emails, read through the Gmail REST API (read-only scope).

Handshake has no public API, so JobScout reads the alert emails Handshake sends
for saved searches. Only messages from the Handshake sender are fetched.

One-time setup:  uv run python -m jobscout.sources.handshake_mail auth
Capture a sample: uv run python -m jobscout.sources.handshake_mail dump
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import httpx

from jobscout.config import Settings
from jobscout.models import Posting
from jobscout.sources.ats import USER_AGENT, SourceError, html_to_text

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
LOOKBACK = "newer_than:8d"
MAX_MESSAGES = 25
GENERIC_LINK_TEXT = {"view job", "view", "apply", "apply now", "see more", "learn more"}

_JOB_LINK = re.compile(
    r'<a\b[^>]*href="(?P<href>[^"]*joinhandshake\.com[^"]*?/jobs/(?P<id>\d+)[^"]*)"[^>]*>'
    r"(?P<text>.*?)</a>",
    re.I | re.S,
)


def parse_alert(html_body: str) -> list[Posting]:
    """Jobs listed in one Handshake alert email.

    Each job is a link to /jobs/<id>; the first link with real text is the title,
    and the next two text lines after it are the employer and location.
    """
    found: dict[str, Posting] = {}
    for m in _JOB_LINK.finditer(html_body):
        job_id = m.group("id")
        title = " ".join(html_to_text(m.group("text")).split())
        if job_id in found or not title or title.lower() in GENERIC_LINK_TEXT:
            continue
        next_link = html_body.find("<a", m.end())
        after = html_body[m.end() : next_link if next_link != -1 else m.end() + 400]
        lines = [line for line in html_to_text(after).splitlines() if line.strip()]
        found[job_id] = Posting(
            source="handshake",
            source_id=job_id,
            url=f"https://app.joinhandshake.com/jobs/{job_id}",
            company=lines[0] if lines else "Unknown",
            title=title,
            location=lines[1] if len(lines) > 1 else "",
        )
    return list(found.values())


def extract_html(payload: dict) -> str:
    """The first text/html body in a Gmail message payload, decoded."""
    if payload.get("mimeType") == "text/html":
        data = (payload.get("body") or {}).get("data")
        if data:
            padded = data + "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    for part in payload.get("parts") or []:
        if found := extract_html(part):
            return found
    return ""


def _alert_bodies(client: httpx.Client, access_token: str, sender: str) -> list[str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = client.get(
        f"{GMAIL_API}/messages",
        params={"q": f"from:{sender} {LOOKBACK}", "maxResults": MAX_MESSAGES},
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    bodies = []
    for ref in resp.json().get("messages", []):
        msg = client.get(
            f"{GMAIL_API}/messages/{ref['id']}",
            params={"format": "full"},
            headers=headers,
            timeout=20,
        )
        msg.raise_for_status()
        bodies.append(extract_html(msg.json().get("payload") or {}))
    return bodies


def fetch_alert_postings(client: httpx.Client, access_token: str, sender: str) -> list[Posting]:
    """Postings from recent Handshake alert emails, deduplicated. Raises SourceError."""
    try:
        bodies = _alert_bodies(client, access_token, sender)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise SourceError(f"Gmail: {exc}") from exc
    postings: dict[str, Posting] = {}
    for body in bodies:
        for p in parse_alert(body):
            postings.setdefault(p.source_id, p)
    return list(postings.values())


def load_credentials(credentials_path: Path, token_path: Path, interactive: bool):
    """OAuth credentials for the read-only Gmail scope. Raises SourceError when re-auth is needed."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            if not interactive:
                raise SourceError(f"Gmail: re-auth needed ({exc})") from exc
        else:
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
    if not interactive:
        raise SourceError("Gmail: re-auth needed (run the auth command)")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def fetch_handshake(client: httpx.Client, settings: Settings) -> list[Posting]:
    creds = load_credentials(
        settings.gmail_credentials_path, settings.gmail_token_path, interactive=False
    )
    return fetch_alert_postings(client, creds.token, settings.handshake_sender)


def main(argv: list[str]) -> int:
    settings = Settings()
    command = argv[1] if len(argv) > 1 else ""
    if command == "auth":
        load_credentials(settings.gmail_credentials_path, settings.gmail_token_path, True)
        print("Gmail authorized.")
        return 0
    if command == "dump":
        creds = load_credentials(settings.gmail_credentials_path, settings.gmail_token_path, True)
        with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
            bodies = _alert_bodies(client, creds.token, settings.handshake_sender)
        if not bodies:
            print("No Handshake emails in the last 8 days.")
            return 1
        out = Path("tests/fixtures/handshake_real.html")
        out.write_text(bodies[0], encoding="utf-8")
        print(f"Wrote {out} ({len(parse_alert(bodies[0]))} jobs parsed).")
        return 0
    print("usage: python -m jobscout.sources.handshake_mail [auth|dump]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
