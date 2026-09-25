# JobScout: Job Finder (Phase 1) Design

Date: 2026-09-25
Status: Approved in brainstorming, pending written-spec review

## Purpose

Find new job postings that fit Quinten's profile every week, rank them, and send
a short Telegram digest. Send an urgent ping when a strong match is about to
close, and remind him before deadlines on jobs he saved. This is phase 1 of 3:

1. **Job finder** (this spec)
2. Inbox tracker: classify employer replies from Gmail and ping on Telegram
3. Application helper: draft a tailored resume and cover letter for a chosen role

Automatic applying is out of scope for every phase.

## Candidate profile (drives filtering and scoring)

- MSc Finance, Nova SBE, graduating **June 2027**; available to start **June 2027 or later**
- U.S. citizen, no sponsorship needed; targeting **U.S. roles**
- Entry level (0 to 2 years). Internship experience: Staff Accountant Intern (Oct 2023 to May 2026)
- Targets: investment analyst, portfolio management, markets / sales & trading,
  Bloomberg-style analytics, corporate finance advisory, strategic finance / FP&A
- Strengths: Python options analytics (Greeks, IV, dealer GEX), Bloomberg,
  Excel modeling, DCF/comps, SQL, accounting close and consolidation

The profile lives in `watchlist.toml` (see Config) plus the resume text in
`profile/resume.md`, so both can change without code edits.

## Project setup

Standalone repo at `C:\Users\quint\projects\JobScout`, independent of WheelTracker.
Same stack: Python 3.11+, `uv`, stdlib `sqlite3`, sync `httpx`, `pydantic` +
`pydantic-settings`, `anthropic`, `pytest`, `ruff`. No ORM, no async.

The Telegram sender (`telegram.py`) and the Claude call pattern
(structured output validated with pydantic, `anthropic.APIError` handled) are
**copied** from `WheelTracker/src/wheel_tracker/news/`, not imported.

## Runtime

Windows Task Scheduler, launched through a `.cmd` wrapper that `cd`s to the
repo and calls `uv` by full path (same pattern as `run_news_alerts.cmd`).

- **Hourly** `python -m jobscout.hourly`: process Telegram commands, send
  urgent pings and deadline reminders, resend any unsent digest.
- **Weekly** (Sunday 18:00 Europe/Lisbon) `python -m jobscout.weekly`: fetch,
  filter, score, send digest.

A file lock prevents the hourly and weekly runs from overlapping.

## Components

```
src/jobscout/
  config.py              # pydantic-settings (.env) + watchlist.toml loader
  models.py              # Posting, Score, JobStatus, etc. (pydantic)
  sources/ats.py         # Greenhouse, Lever, Ashby public feeds
  sources/handshake_mail.py  # Handshake alert emails via Gmail API
  filter.py              # hard rules, pure functions
  score.py               # Claude scoring, returns Score
  store.py               # sqlite3 persistence
  digest.py              # message formatting, pure functions
  telegram.py            # send + getUpdates polling
  commands.py            # /save /applied /skip /list parsing and effects
  weekly.py, hourly.py   # entrypoints wiring the above
```

### Sources

Each source returns `list[Posting]` and raises `SourceError` on failure.

- **Greenhouse:** `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
- **Lever:** `GET https://api.lever.co/v0/postings/{company}?mode=json`
- **Ashby:** `GET https://api.ashbyhq.com/posting-api/job-board/{name}`
- **Handshake mail:** Gmail API with scope `gmail.readonly`, query
  `from:handshake newer_than:8d` (exact sender confirmed during implementation).
  Parse job title, employer, location and link from each alert email. Only these
  messages are read. OAuth token stored locally in `token.json` (gitignored).

`Posting` fields: `source`, `source_id`, `url`, `company`, `title`,
`location`, `description` (plain text, truncated to 12k chars), `posted_at`
(optional), `deadline` (optional, when the source states one), `fetched_at`.

Identity: `job_id = sha1(source + source_id)`; for Handshake, `source_id` is
the Handshake job ID parsed from the link. A `content_hash` of title and
description decides whether a known posting changed and needs rescoring.

### Filter (rules)

Pure function `apply_rules(posting, profile) -> RuleResult(keep: bool, reason: str | None)`.
Rejects when:

- Title matches seniority words: senior, sr., vp, vice president, director,
  manager, principal, head of, lead, or a level of II and above (II, III, 2, 3).
  Matching is whole-word and case-insensitive, so "Asset Management" and
  "2027 Analyst" are not rejected; a numeric level only counts when it directly
  follows the role word ("Analyst II", "Associate 2").
- Description requires 3+ years (regex over "N+ years", "N-M years", "minimum of N years").
- Location is outside the U.S. and the company is not flagged `allow_non_us`
  in the watchlist. "Remote" with no country counts as U.S.

Rejection reasons are stored so a rule can be audited and tuned.

### Score (Claude)

Called only for postings that pass the rules and are new or changed. The model
is set in config (default `claude-sonnet-5`). Input: profile, resume text,
posting. Output validated as:

```
Score:
  fit: int 1-10
  timing: "fits_june_2027" | "unclear" | "needs_start_now"
  deadline: date | null      # from posting text, if stated
  reason: str                # one line, max 140 chars
```

A `needs_start_now` verdict caps `fit` at 5 so such roles stay out of the
digest. On API error or validation failure the posting stays `unscored` and is
retried next run (max 3 attempts, then marked `score_failed` and listed as a
count in the digest).

### Store (SQLite, `jobscout.db`)

- `jobs`: job_id PK, source, source_id, url, company, title, location,
  description, content_hash, posted_at, deadline, first_seen, last_seen
- `rule_results`: job_id, keep, reason, checked_at
- `scores`: job_id, content_hash, fit, timing, deadline, reason, model, scored_at, attempts
- `status`: job_id, state (`new|saved|applied|skipped`), updated_at
- `alerts`: job_id, kind (`urgent|reminder`), sent_at, UNIQUE(job_id, kind)
- `digests`: id, created_at, body, sent_at (null until delivered)
- `digest_items`: digest_id, position (1-based number shown in the message), job_id
- `telegram_offset`: single row, last processed update_id

Short numbers in commands (`/applied 3`) map through the most recent digest's
`digest_items`. `/list` prints saved and applied jobs with their own numbers.

### Digest and alerts

Rules follow the existing news-digest preferences: compact, no extra sections.

- **Weekly digest:** top 8 jobs with `fit >= 6`, sorted by fit desc then
  deadline asc (unknown deadlines last). Each item is two lines:
  `3. ICONIQ, Financial Advisory Analyst · 9/10 · closes Oct 30`
  `Summer 2027 start, options trading in role · <link>`
  Footer: counts only (`23 more below 6 · 2 sources failed: Lever/harrisonst`).
- **Urgent ping:** a job with `fit >= 8` and a deadline within 7 days, sent once,
  by whichever run (weekly or hourly) sees it first.
- **Reminder:** a `saved` job with a deadline 3 days away, sent once.
- **Quiet hours:** hourly pings are held between 23:00 and 08:00 Lisbon time.

### Commands (Telegram replies)

`/save N`, `/applied N`, `/skip N`, `/list`. Only messages from the configured
`TELEGRAM_CHAT_ID` are accepted. Unknown commands get a one-line help reply.

## Config

`.env` (gitignored): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `GMAIL_CREDENTIALS_PATH`, optional `ANTHROPIC_MODEL`.

`watchlist.toml`:

```toml
[profile]
available_from = "2027-06-01"
country = "US"
max_years_required = 2
targets = ["investment analyst", "portfolio management", "sales and trading", ...]

[[company]]
name = "ICONIQ"
ats = "greenhouse"
token = "iconiq"

[[company]]
name = "Harrison Street"
ats = "lever"
token = "harrisonst"
```

Seed watchlist: the firms from the September 2026 saved-jobs list whose ATS can
be identified (ICONIQ, Harrison Street, and others confirmed during setup).
Firms on custom portals (Bloomberg, HSBC, Nomura) rely on Handshake mail.

## Error handling

- One failing source never stops the run; it is named in the digest footer.
- Claude unavailable: postings stay unscored and are retried; nothing is sent unscored.
- Telegram failure: digest row keeps `sent_at = null`; the next hourly run resends it.
- Gmail token expired or revoked: that source fails with a clear log line and a
  digest footer note ("Gmail: re-auth needed").
- Every run appends to `jobscout.log`.

## Testing

- Recorded JSON fixtures for Greenhouse, Lever and Ashby, and a saved Handshake
  alert email, drive the source parsers.
- Unit tests: rule filter (seniority, years regex, location), job identity and
  change detection, digest formatting and ordering, command parsing and state
  changes, urgent/reminder timing with an injected clock, quiet hours.
- Scoring tests use a fake Claude client returning fixed `Score` JSON, including
  invalid output to exercise retries.
- One live scoring test is skipped unless `ANTHROPIC_API_KEY` is set.

## Out of scope (phase 1)

Automatic applying, inbox reply tracking, resume/cover letter drafting, a web
dashboard, and scraping Handshake or LinkedIn pages directly.
