"""Check each watchlist company's job-board token: uv run python -m jobscout.check"""

from __future__ import annotations

import sys

import httpx

from jobscout.config import Settings, load_watchlist
from jobscout.sources.ats import USER_AGENT, SourceError, fetch_company


def main() -> int:
    watchlist = load_watchlist(Settings().watchlist_path)
    failures = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for company in watchlist.company:
            label = f"{company.name:<24} {company.ats}:{company.token}"
            try:
                count = len(fetch_company(client, company))
            except SourceError as exc:
                failures += 1
                print(f"FAIL  {label}  {exc}")
            else:
                print(f"ok    {label}  {count} postings")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
