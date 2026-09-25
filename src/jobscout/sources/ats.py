"""Public job-board feeds (Greenhouse, Lever, Ashby). No authentication needed."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from jobscout.config import Company
from jobscout.models import Posting

MAX_DESCRIPTION = 12_000
USER_AGENT = "JobScout/0.1 (personal job search)"

_BREAK = re.compile(r"<(?:br|/p|/li|/h\d|/div|/tr)\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\xa0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


class SourceError(Exception):
    """A source could not be read; the run continues without it."""


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped, as Greenhouse sends it) to plain text with line breaks."""
    text = html.unescape(raw)
    text = _BREAK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    text = _SPACES.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = _BLANK_LINES.sub("\n\n", "\n".join(lines))
    return text.strip()[:MAX_DESCRIPTION]


def _get_json(client: httpx.Client, url: str) -> Any:
    try:
        resp = client.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError(f"{url}: {exc}") from exc


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fetch_greenhouse(client: httpx.Client, company: Company) -> list[Posting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company.token}/jobs?content=true"
    data = _get_json(client, url)
    return [
        Posting(
            source=f"greenhouse:{company.token}",
            source_id=str(job["id"]),
            url=job["absolute_url"],
            company=company.name,
            title=job["title"],
            location=(job.get("location") or {}).get("name", ""),
            description=html_to_text(job.get("content") or ""),
            posted_at=_parse_iso(job.get("updated_at")),
        )
        for job in data["jobs"]
    ]


def fetch_lever(client: httpx.Client, company: Company) -> list[Posting]:
    data = _get_json(client, f"https://api.lever.co/v0/postings/{company.token}?mode=json")
    postings = []
    for job in data:
        parts = [job.get("descriptionPlain") or ""]
        for section in job.get("lists") or []:
            parts.append(section.get("text") or "")
            parts.append(html_to_text(section.get("content") or ""))
        parts.append(job.get("additionalPlain") or "")
        created = job.get("createdAt")
        postings.append(
            Posting(
                source=f"lever:{company.token}",
                source_id=job["id"],
                url=job["hostedUrl"],
                company=company.name,
                title=job["text"],
                location=(job.get("categories") or {}).get("location") or "",
                description="\n\n".join(p for p in parts if p)[:MAX_DESCRIPTION],
                posted_at=datetime.fromtimestamp(created / 1000, UTC) if created else None,
            )
        )
    return postings


def fetch_ashby(client: httpx.Client, company: Company) -> list[Posting]:
    data = _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{company.token}")
    postings = []
    for job in data["jobs"]:
        if job.get("isListed") is False:
            continue
        url = job["jobUrl"]
        description = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
        postings.append(
            Posting(
                source=f"ashby:{company.token}",
                source_id=str(job.get("id") or url),
                url=url,
                company=company.name,
                title=job["title"],
                location=job.get("location") or "",
                description=description[:MAX_DESCRIPTION],
                posted_at=_parse_iso(job.get("publishedAt")),
            )
        )
    return postings


_FETCHERS: dict[str, Callable[[httpx.Client, Company], list[Posting]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def fetch_company(client: httpx.Client, company: Company) -> list[Posting]:
    """All open postings for one watchlist company. Raises SourceError."""
    try:
        return _FETCHERS[company.ats](client, company)
    except (KeyError, TypeError, AttributeError) as exc:
        raise SourceError(f"{company.name}: unexpected response shape ({exc!r})") from exc
