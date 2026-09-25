# JobScout Job Finder Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A weekly job finder that pulls postings from company job boards and Handshake alert emails, filters and Claude-scores them against Quinten's profile, and sends a compact Telegram digest plus urgent/deadline pings, with `/save`, `/applied`, `/skip`, `/list` replies.

**Architecture:** Small pure modules (filter, digest formatting, command parsing, scoring post-processing) around a single SQLite `Store`. Two entrypoints, `jobscout.weekly` and `jobscout.hourly`, wire real sources/Claude/Telegram into `run_weekly` / `run_hourly` functions that take injected callables so they are fully testable. Windows Task Scheduler runs them through `.cmd` launchers.

**Tech Stack:** Python 3.11, uv, stdlib sqlite3/tomllib, httpx (sync), pydantic + pydantic-settings, anthropic SDK (`messages.parse`), google-auth + google-auth-oauthlib (Gmail OAuth only), tzdata, pytest + pytest-httpx, ruff.

**Spec:** `docs/superpowers/specs/2026-09-25-job-finder-design.md`

**Conventions (all tasks):**
- Run everything from `C:\Users\quint\projects\JobScout` in Git Bash.
- All `now` values are timezone-aware UTC `datetime`s. Deadlines are `date`s. "Today" means the Europe/Lisbon date.
- Before each commit: `uv run ruff format . && uv run ruff check .` must be clean.
- Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File map

```
pyproject.toml, .gitignore, .env.example, watchlist.toml, README.md
profile/resume.md                      # gitignored, candidate resume text
scripts/run_weekly.cmd, run_hourly.cmd, run_hidden.vbs
src/jobscout/
  __init__.py
  models.py        # Posting, RuleResult, Score, DigestRow, Timing, JobState
  config.py        # Settings (.env), Profile, Company, Watchlist, load_watchlist
  filter.py        # required_years, is_non_us, apply_rules
  store.py         # Store (sqlite3)
  sources/__init__.py
  sources/ats.py             # SourceError, html_to_text, fetch_company (Greenhouse/Lever/Ashby)
  sources/handshake_mail.py  # parse_alert, extract_html, fetch_alert_postings, load_credentials, CLI
  score.py         # ClaudeScorer, ScoreError, to_score, make_client
  digest.py        # format_row, format_digest, format_urgent, format_reminder, format_list
  telegram.py      # send_message (copied), get_updates, TelegramError
  commands.py      # Command, parse_command, handle
  alerts.py        # LISBON, is_quiet, send_alerts
  lock.py          # file_lock, LockBusy
  weekly.py        # Source, run_weekly, build_sources, main
  hourly.py        # process_commands, resend_unsent, run_hourly, main
  check.py         # watchlist token checker CLI
tests/
  helpers.py, conftest.py
  fixtures/greenhouse.json, lever.json, ashby.json, handshake_alert.html
  test_models.py, test_config.py, test_filter.py, test_store.py, test_ats.py,
  test_handshake_mail.py, test_score.py, test_digest.py, test_telegram.py,
  test_commands.py, test_alerts.py, test_lock.py, test_weekly.py, test_hourly.py,
  test_live_score.py
```

---

## Chunk 1: Foundation

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/jobscout/__init__.py`, `src/jobscout/sources/__init__.py`, `tests/helpers.py`, `tests/conftest.py`, `tests/test_smoke.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "jobscout"
version = "0.1.0"
description = "Weekly job finder: job boards + Handshake alerts, Claude-scored, Telegram digest."
readme = "README.md"
authors = [{ name = "Quinten Goodman", email = "Quinten@goodmansonline.com" }]
requires-python = ">=3.11"
dependencies = [
    "anthropic>=1.4.0",
    "google-auth>=2.40.0",
    "google-auth-oauthlib>=1.2.0",
    "httpx>=0.28.1",
    "pydantic>=2.13.3",
    "pydantic-settings>=2.14.0",
    "tzdata>=2025.2",
]

[build-system]
requires = ["uv_build>=0.11.8,<0.12.0"]
build-backend = "uv_build"

[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-httpx>=0.36.2",
    "ruff>=0.15.12",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
addopts = "-ra -m 'not live'"
markers = ["live: calls real external APIs (needs keys)"]
```

- [ ] **Step 2: Replace `.gitignore`**

```
.env
*.db
*.log
*.lock
token.json
credentials.json
profile/
tests/fixtures/handshake_real.html
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 3: Write `.env.example`**

```
ANTHROPIC_API_KEY=
ANTHROPIC_WORKSPACE_ID=
ANTHROPIC_MODEL=claude-sonnet-5
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_TOKEN_PATH=token.json
HANDSHAKE_ENABLED=true
HANDSHAKE_SENDER=joinhandshake.com
```

- [ ] **Step 4: Package files**

`src/jobscout/__init__.py`:
```python
"""JobScout: weekly job finder."""
```

`src/jobscout/sources/__init__.py`:
```python
"""Job posting sources."""
```

- [ ] **Step 5: Test helpers** (fleshed out in later tasks; start with the constants)

`tests/helpers.py`:
```python
"""Shared test helpers (importable because pytest adds tests/ to sys.path)."""

from __future__ import annotations

from datetime import UTC, date, datetime

# Sunday 2026-09-27 17:00 UTC == 18:00 in Lisbon (WEST, UTC+1): the weekly slot.
NOW = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
TODAY = date(2026, 9, 27)
```

`tests/conftest.py`:
```python
"""Pytest fixtures."""
```

`tests/test_smoke.py`:
```python
import jobscout


def test_package_imports():
    assert jobscout.__doc__
```

- [ ] **Step 6: Create the venv on the user's Python and sync**

The desktop app's own uv-managed Pythons are invisible to the user's terminal, so pin the user's install:

Run: `uv venv --python "C:/Users/quint/AppData/Local/Programs/Python/Python311/python.exe" && uv sync`
Expected: `.venv` created, dependencies installed without errors.

- [ ] **Step 7: Run tests**

Run: `uv run pytest`
Expected: `1 passed`

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: scaffold jobscout package

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Domain models

**Files:**
- Create: `src/jobscout/models.py`
- Test: `tests/test_models.py`
- Modify: `tests/helpers.py`

- [ ] **Step 1: Add `make_posting` to `tests/helpers.py`** (append)

```python
from jobscout.models import Posting


def make_posting(**overrides) -> Posting:
    fields = {
        "source": "greenhouse:iconiq",
        "source_id": "1",
        "url": "https://example.com/jobs/1",
        "company": "ICONIQ",
        "title": "Analyst, Financial Advisory",
        "location": "New York, NY",
        "description": "Entry-level role. 0-2 years of experience.",
    }
    fields.update(overrides)
    return Posting(**fields)
```

(Move the `from jobscout.models import Posting` line up with the other imports.)

- [ ] **Step 2: Write the failing tests**

`tests/test_models.py`:
```python
import pytest
from helpers import make_posting
from pydantic import ValidationError

from jobscout.models import Score


def test_job_id_depends_on_source_and_source_id_only():
    a = make_posting(title="A")
    b = make_posting(title="B")
    assert a.job_id == b.job_id
    assert len(a.job_id) == 16
    assert make_posting(source_id="2").job_id != a.job_id
    assert make_posting(source="lever:x").job_id != a.job_id


def test_content_hash_tracks_title_and_description():
    base = make_posting()
    assert make_posting(description="changed").content_hash != base.content_hash
    assert make_posting(title="changed").content_hash != base.content_hash
    assert make_posting(location="Boston, MA").content_hash == base.content_hash


def test_score_bounds():
    Score(fit=1, timing="unclear", reason="ok")
    with pytest.raises(ValidationError):
        Score(fit=11, timing="unclear", reason="ok")
    with pytest.raises(ValidationError):
        Score(fit=5, timing="someday", reason="ok")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'jobscout.models'`

- [ ] **Step 4: Implement `src/jobscout/models.py`**

```python
"""Domain models shared across JobScout."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Timing = Literal["fits_june_2027", "unclear", "needs_start_now"]
JobState = Literal["new", "saved", "applied", "skipped"]


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Posting(BaseModel):
    """One job posting as read from a source."""

    source: str  # e.g. "greenhouse:iconiq", "lever:harrisonst", "handshake"
    source_id: str
    url: str
    company: str
    title: str
    location: str = ""
    description: str = ""
    posted_at: datetime | None = None
    deadline: date | None = None

    @property
    def job_id(self) -> str:
        """Stable identity: the same source + id is the same job."""
        return _short_hash(f"{self.source}:{self.source_id}")

    @property
    def content_hash(self) -> str:
        """Changes when the posting text changes, which triggers a rescore."""
        return _short_hash(f"{self.title}\n{self.description}")


class RuleResult(BaseModel):
    keep: bool
    reason: str | None = None


class Score(BaseModel):
    fit: int = Field(ge=1, le=10)
    timing: Timing
    deadline: date | None = None
    reason: str = Field(max_length=140)


class DigestRow(BaseModel):
    """A scored job as shown in a Telegram message."""

    num: int  # permanent #N the user types in commands
    job_id: str
    company: str
    title: str
    url: str
    fit: int
    reason: str
    deadline: date | None = None
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: posting, score and digest-row models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Config and watchlist

**Files:**
- Create: `src/jobscout/config.py`, `watchlist.toml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `No module named 'jobscout.config'`

- [ ] **Step 3: Implement `src/jobscout/config.py`**

```python
"""Settings from .env, and the candidate profile + company watchlist from watchlist.toml."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    anthropic_model: str = "claude-sonnet-5"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    gmail_credentials_path: Path = Path("credentials.json")
    gmail_token_path: Path = Path("token.json")
    handshake_enabled: bool = True
    handshake_sender: str = "joinhandshake.com"
    db_path: Path = Path("jobscout.db")
    watchlist_path: Path = Path("watchlist.toml")
    resume_path: Path = Path("profile/resume.md")


class Profile(BaseModel):
    available_from: date
    country: str = "US"
    max_years_required: int = 2
    targets: list[str] = Field(default_factory=list)
    summary: str = ""


class Company(BaseModel):
    name: str
    ats: Literal["greenhouse", "lever", "ashby"]
    token: str
    allow_non_us: bool = False


class Watchlist(BaseModel):
    profile: Profile
    company: list[Company] = Field(default_factory=list)


def load_watchlist(path: Path) -> Watchlist:
    with path.open("rb") as f:
        return Watchlist.model_validate(tomllib.load(f))
```

- [ ] **Step 4: Write `watchlist.toml`**

```toml
# Candidate profile (used by the rules filter and the Claude scorer) and the
# companies whose public job boards are checked every week.
# Check tokens with: uv run python -m jobscout.check

[profile]
available_from = 2027-06-01
country = "US"
max_years_required = 2
targets = [
    "investment analyst (equity research, public or private markets)",
    "portfolio management analyst",
    "markets / sales and trading analyst",
    "financial data analytics and sales (e.g. Bloomberg A&S)",
    "wealth or financial advisory analyst",
    "corporate finance advisory analyst",
    "strategic finance / FP&A analyst",
]
summary = """MSc Finance, Nova SBE (June 2027). B.S. Finance and B.S. Management, Arizona State \
University (major GPA 4.0). U.S. citizen, no sponsorship needed. Builds Python options \
analytics (Greeks, implied volatility, dealer gamma exposure) and uses Bloomberg. Strong Excel \
modeling, DCF and comps. 2.5 years as a staff accountant intern (consolidation, variance \
analysis, process automation). Member of the Nova Students Portfolio student-managed fund."""

[[company]]
name = "ICONIQ"
ats = "greenhouse"
token = "iconiq"

[[company]]
name = "Harrison Street"
ats = "lever"
token = "harrisonst"
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: settings and watchlist config

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Chunk 2: Filtering and storage

### Task 4: Rules filter

**Files:**
- Create: `src/jobscout/filter.py`
- Test: `tests/test_filter.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_filter.py`:
```python
from datetime import date

import pytest
from helpers import make_posting

from jobscout.config import Profile
from jobscout.filter import apply_rules, is_non_us, required_years

PROFILE = Profile(available_from=date(2027, 6, 1), max_years_required=2)


@pytest.mark.parametrize(
    "title",
    [
        "Senior Analyst",
        "Sr. Financial Analyst",
        "VP, Credit",
        "Director of Research",
        "Portfolio Manager",
        "Lead Analyst",
        "Head of Trading",
        "Strategic Finance Analyst II",
        "Associate 2, Private Credit",
        "Principal, Investments",
    ],
)
def test_rejects_senior_titles(title):
    result = apply_rules(make_posting(title=title), PROFILE)
    assert result.keep is False
    assert result.reason


@pytest.mark.parametrize(
    "title",
    [
        "Analyst, Asset Management",
        "2027 Portfolio Management Analyst",
        "(#5213032007) Financial Analyst I, AD&S",
        "Leadership Development Program Analyst",
        "Investment Analyst / Associate",
        "Markets Sales and Trading Graduate",
    ],
)
def test_keeps_entry_level_titles(title):
    assert apply_rules(make_posting(title=title), PROFILE).keep is True


@pytest.mark.parametrize(
    ("text", "years"),
    [
        ("Requires 5+ years of relevant experience.", 5),
        ("3-5 years experience in FP&A", 3),
        ("3 to 5 years of experience", 3),
        ("minimum of 4 years of professional experience", 4),
        ("0–2 years of experience in finance", 0),
        ("2+ years of equity research/investment analysis experience", 2),
        ("Founded 20 years ago, we invest in growth.", None),
        ("", None),
        ("5+ years of experience preferred; 1 year of experience required", 1),
    ],
)
def test_required_years(text, years):
    assert required_years(text) == years


def test_rejects_too_many_years():
    result = apply_rules(make_posting(description="5+ years of relevant experience"), PROFILE)
    assert result.keep is False
    assert result.reason == "requires 5+ years"


def test_keeps_two_years():
    assert apply_rules(make_posting(description="2+ years of experience"), PROFILE).keep


@pytest.mark.parametrize(
    ("location", "non_us"),
    [
        ("London, England", True),
        ("Toronto, Canada", True),
        ("Remote - UK", True),
        ("Lisbon, Portugal", True),
        ("New York, NY", False),
        ("San Francisco, CA; London", False),
        ("New York or London", False),
        ("Remote", False),
        ("", False),
        ("Chicago, IL", False),
    ],
)
def test_is_non_us(location, non_us):
    assert is_non_us(location) is non_us


def test_non_us_rejected_unless_allowed():
    p = make_posting(location="London, England")
    rejected = apply_rules(p, PROFILE)
    assert rejected.keep is False
    assert rejected.reason == "non-US: London, England"
    assert apply_rules(p, PROFILE, allow_non_us=True).keep is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_filter.py -v`
Expected: FAIL, `No module named 'jobscout.filter'`

- [ ] **Step 3: Implement `src/jobscout/filter.py`**

```python
"""Hard rules that drop obvious non-fits before any Claude call. Pure functions."""

from __future__ import annotations

import re

from jobscout.config import Profile
from jobscout.models import Posting, RuleResult

# Whole-word seniority markers; "Management" and "Leadership" do not match.
_SENIOR = re.compile(
    r"\b(?:senior|sr|vp|svp|evp|vice president|director|manager|principal|head of|lead)\b",
    re.I,
)
# A level of II and above directly after a role word: "Analyst II", "Associate 2".
_LEVEL = re.compile(
    r"\b(?:analyst|associate|specialist|accountant|engineer|consultant)\s+(?:ii|iii|iv|v|2|3|4)\b",
    re.I,
)
# "5+ years of relevant experience", "3-5 years experience", "minimum of 4 years ... experience".
_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:\+|(?:-|–|to)\s*\d{1,2})?\s*\+?\s*years?[’']?\s+"
    r"(?:of\s+)?(?:[a-z/&,\-]+\s+){0,6}?experience",
    re.I,
)
_NON_US = re.compile(
    r"\b(?:united kingdom|uk|england|scotland|london|canada|toronto|vancouver|montreal|india|"
    r"bangalore|bengaluru|mumbai|singapore|hong kong|germany|berlin|frankfurt|munich|france|"
    r"paris|ireland|dublin|netherlands|amsterdam|switzerland|zurich|geneva|portugal|lisbon|"
    r"spain|madrid|italy|milan|japan|tokyo|australia|sydney|mexico|brazil|poland|emea|apac)\b",
    re.I,
)
_US_WORDS = re.compile(r"\b(?:united states|usa|u\.s\.?|us|new york|nyc)\b", re.I)
_US_STATE = re.compile(
    r",\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|"
    r"NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
)


def required_years(text: str) -> int | None:
    """Smallest 'N years ... experience' requirement stated, or None if none is stated."""
    found = [int(m.group(1)) for m in _YEARS.finditer(text)]
    return min(found) if found else None


def is_non_us(location: str) -> bool:
    """True only when the location clearly names a non-U.S. place and no U.S. one."""
    if not _NON_US.search(location):
        return False
    return not (_US_WORDS.search(location) or _US_STATE.search(location))


def apply_rules(posting: Posting, profile: Profile, allow_non_us: bool = False) -> RuleResult:
    if m := _SENIOR.search(posting.title):
        return RuleResult(keep=False, reason=f"seniority: {m.group(0)}")
    if m := _LEVEL.search(posting.title):
        return RuleResult(keep=False, reason=f"level: {m.group(0)}")
    years = required_years(posting.description)
    if years is not None and years > profile.max_years_required:
        return RuleResult(keep=False, reason=f"requires {years}+ years")
    if not allow_non_us and is_non_us(posting.location):
        return RuleResult(keep=False, reason=f"non-US: {posting.location}")
    return RuleResult(keep=True)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_filter.py -v`
Expected: all pass. If a regex case fails, fix the regex (not the test) unless the test contradicts the spec.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: rules filter for seniority, years required and location

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Store, part 1 (jobs, rules, scores)

**Files:**
- Create: `src/jobscout/store.py`
- Test: `tests/test_store.py`
- Modify: `tests/helpers.py`, `tests/conftest.py`

- [ ] **Step 1: Add fixtures and helpers**

`tests/conftest.py`:
```python
"""Pytest fixtures."""

import sqlite3

import pytest

from jobscout.store import Store


@pytest.fixture
def store() -> Store:
    return Store(sqlite3.connect(":memory:"))
```

Append to `tests/helpers.py` (merge imports at top):
```python
from jobscout.models import RuleResult, Score


def add_scored(store, now, fit, deadline=None, timing="fits_june_2027", **posting_fields):
    """Insert a kept, scored posting and return it."""
    p = make_posting(**posting_fields)
    store.upsert_posting(p, now)
    store.record_rule(p.job_id, RuleResult(keep=True), now)
    score = Score(fit=fit, timing=timing, deadline=deadline, reason=f"fit {fit}")
    store.save_score(p.job_id, p.content_hash, score, "test-model", now)
    return p


def num_of(store, posting) -> int:
    row = store.conn.execute("SELECT num FROM jobs WHERE job_id = ?", (posting.job_id,)).fetchone()
    return row[0]
```

- [ ] **Step 2: Write the failing tests**

`tests/test_store.py`:
```python
from datetime import timedelta

from helpers import NOW, add_scored, make_posting

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
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL, `No module named 'jobscout.store'`

- [ ] **Step 4: Implement `src/jobscout/store.py`** (part 1; part 2 appends methods)

```python
"""SQLite persistence for JobScout.

Timestamps are ISO-8601 strings of UTC datetimes and deadlines are ISO dates, so
plain string comparison orders both correctly. Callers must pass UTC `now` values.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from jobscout.models import DigestRow, JobState, Posting, RuleResult, Score

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    num INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    posted_at TEXT,
    deadline TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_results (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    keep INTEGER NOT NULL,
    reason TEXT,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    content_hash TEXT NOT NULL,
    fit INTEGER,
    timing TEXT,
    deadline TEXT,
    reason TEXT,
    model TEXT,
    scored_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS status (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE (job_id, kind)
);
CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS digest_items (
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    position INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    PRIMARY KEY (digest_id, position)
);
CREATE TABLE IF NOT EXISTS telegram_offset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    update_id INTEGER NOT NULL
);
"""

MAX_ATTEMPTS = 3
_DEADLINE = "COALESCE(j.deadline, s.deadline)"
_ROWS = f"""
SELECT j.num, j.job_id, j.company, j.title, j.url, s.fit, s.reason,
       {_DEADLINE} AS deadline, COALESCE(st.state, 'new') AS state
FROM jobs j
JOIN scores s ON s.job_id = j.job_id
LEFT JOIN status st ON st.job_id = j.job_id
"""


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def _posting(r: sqlite3.Row) -> Posting:
    return Posting(
        source=r["source"],
        source_id=r["source_id"],
        url=r["url"],
        company=r["company"],
        title=r["title"],
        location=r["location"],
        description=r["description"],
        posted_at=datetime.fromisoformat(r["posted_at"]) if r["posted_at"] else None,
        deadline=date.fromisoformat(r["deadline"]) if r["deadline"] else None,
    )


def _row(r: sqlite3.Row) -> DigestRow:
    return DigestRow(
        num=r["num"],
        job_id=r["job_id"],
        company=r["company"],
        title=r["title"],
        url=r["url"],
        fit=r["fit"],
        reason=r["reason"] or "",
        deadline=date.fromisoformat(r["deadline"]) if r["deadline"] else None,
    )


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        self.conn = conn

    @classmethod
    def open(cls, path: Path | str) -> Store:
        return cls(sqlite3.connect(path))

    # --- postings, rules, scores -------------------------------------------------

    def upsert_posting(self, p: Posting, now: datetime) -> Literal["new", "changed", "same"]:
        ts = now.isoformat()
        old = self.conn.execute(
            "SELECT content_hash FROM jobs WHERE job_id = ?", (p.job_id,)
        ).fetchone()
        values = (
            p.url,
            p.company,
            p.title,
            p.location,
            p.description,
            p.content_hash,
            _iso(p.posted_at),
            _iso(p.deadline),
        )
        with self.conn:
            if old is None:
                self.conn.execute(
                    "INSERT INTO jobs (job_id, source, source_id, url, company, title, location,"
                    " description, content_hash, posted_at, deadline, first_seen, last_seen)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (p.job_id, p.source, p.source_id, *values, ts, ts),
                )
                return "new"
            self.conn.execute(
                "UPDATE jobs SET url = ?, company = ?, title = ?, location = ?, description = ?,"
                " content_hash = ?, posted_at = ?, deadline = ?, last_seen = ? WHERE job_id = ?",
                (*values, ts, p.job_id),
            )
        return "same" if old["content_hash"] == p.content_hash else "changed"

    def record_rule(self, job_id: str, result: RuleResult, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO rule_results (job_id, keep, reason, checked_at)"
                " VALUES (?, ?, ?, ?)",
                (job_id, int(result.keep), result.reason, now.isoformat()),
            )

    def jobs_to_score(self, since: datetime, max_attempts: int = MAX_ATTEMPTS) -> list[Posting]:
        """Kept jobs seen since `since` with no score for their current text."""
        rows = self.conn.execute(
            "SELECT j.* FROM jobs j"
            " JOIN rule_results r ON r.job_id = j.job_id AND r.keep = 1"
            " LEFT JOIN scores s ON s.job_id = j.job_id"
            " WHERE j.last_seen >= ?"
            " AND (s.job_id IS NULL OR s.content_hash != j.content_hash"
            "      OR (s.fit IS NULL AND s.attempts < ?))"
            " ORDER BY j.num",
            (since.isoformat(), max_attempts),
        ).fetchall()
        return [_posting(r) for r in rows]

    def save_score(
        self, job_id: str, content_hash: str, score: Score, model: str, now: datetime
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO scores (job_id, content_hash, fit, timing, deadline,"
                " reason, model, scored_at, attempts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    job_id,
                    content_hash,
                    score.fit,
                    score.timing,
                    _iso(score.deadline),
                    score.reason,
                    model,
                    now.isoformat(),
                ),
            )

    def record_score_failure(self, job_id: str, content_hash: str, now: datetime) -> None:
        """Count a failed attempt; attempts restart at 1 when the posting text changed."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO scores (job_id, content_hash, fit, scored_at, attempts)"
                " VALUES (?, ?, NULL, ?, 1)"
                " ON CONFLICT(job_id) DO UPDATE SET"
                "  attempts = CASE WHEN scores.content_hash = excluded.content_hash"
                "                   AND scores.fit IS NULL"
                "              THEN scores.attempts + 1 ELSE 1 END,"
                "  content_hash = excluded.content_hash, fit = NULL, timing = NULL,"
                "  deadline = NULL, reason = NULL, scored_at = excluded.scored_at",
                (job_id, content_hash, now.isoformat()),
            )

    def count_score_failed(self, since: datetime, max_attempts: int = MAX_ATTEMPTS) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM scores s JOIN jobs j ON j.job_id = s.job_id"
            " WHERE s.fit IS NULL AND s.attempts >= ? AND j.last_seen >= ?",
            (max_attempts, since.isoformat()),
        ).fetchone()[0]

    def count_below(self, min_fit: int, scored_after: datetime) -> int:
        """Jobs scored after `scored_after` (normally the last digest) under the cut-off."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM scores WHERE fit IS NOT NULL AND fit < ? AND scored_at > ?",
            (min_fit, scored_after.isoformat()),
        ).fetchone()[0]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: sqlite store for jobs, rule results and scores

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Store, part 2 (digests, status, alerts, Telegram offset)

**Files:**
- Modify: `src/jobscout/store.py` (append methods to `Store`)
- Test: `tests/test_store.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_store.py`**

First change the imports at the top of the file to:

```python
from datetime import date, timedelta

from helpers import NOW, TODAY, add_scored, make_posting, num_of

from jobscout.models import RuleResult
```

Then append:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store.py -v`
Expected: the new tests FAIL with `AttributeError: 'Store' object has no attribute ...`

- [ ] **Step 3: Append methods to `Store` in `src/jobscout/store.py`**

```python
# --- digests -------------------------------------------------------------------


def digest_candidates(
    self, min_fit: int, since: datetime, today: date, limit: int
) -> list[DigestRow]:
    """Best new, still-open jobs never shown in a digest."""
    rows = self.conn.execute(
        _ROWS + " WHERE s.fit >= ? AND j.last_seen >= ?"
        " AND COALESCE(st.state, 'new') = 'new'"
        f" AND ({_DEADLINE} IS NULL OR {_DEADLINE} >= ?)"
        " AND j.job_id NOT IN (SELECT job_id FROM digest_items)"
        f" ORDER BY s.fit DESC, {_DEADLINE} IS NULL, {_DEADLINE}, j.num LIMIT ?",
        (min_fit, since.isoformat(), today.isoformat(), limit),
    ).fetchall()
    return [_row(r) for r in rows]


def create_digest(self, body: str, job_ids: list[str], now: datetime) -> int:
    with self.conn:
        cur = self.conn.execute(
            "INSERT INTO digests (created_at, body) VALUES (?, ?)", (now.isoformat(), body)
        )
        digest_id = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO digest_items (digest_id, position, job_id) VALUES (?, ?, ?)",
            [(digest_id, i, job_id) for i, job_id in enumerate(job_ids, start=1)],
        )
    return digest_id


def last_digest_at(self) -> datetime | None:
    row = self.conn.execute("SELECT MAX(created_at) AS at FROM digests").fetchone()
    return datetime.fromisoformat(row["at"]) if row["at"] else None


def mark_digest_sent(self, digest_id: int, now: datetime) -> None:
    with self.conn:
        self.conn.execute(
            "UPDATE digests SET sent_at = ? WHERE id = ?", (now.isoformat(), digest_id)
        )


def unsent_digests(self) -> list[tuple[int, str]]:
    rows = self.conn.execute(
        "SELECT id, body FROM digests WHERE sent_at IS NULL ORDER BY id"
    ).fetchall()
    return [(r["id"], r["body"]) for r in rows]


# --- status --------------------------------------------------------------------


def set_status(self, num: int, state: JobState, now: datetime) -> tuple[str, str] | None:
    """Set a job's state by its #num. Returns (company, title), or None if unknown."""
    job = self.conn.execute(
        "SELECT job_id, company, title FROM jobs WHERE num = ?", (num,)
    ).fetchone()
    if job is None:
        return None
    with self.conn:
        self.conn.execute(
            "INSERT OR REPLACE INTO status (job_id, state, updated_at) VALUES (?, ?, ?)",
            (job["job_id"], state, now.isoformat()),
        )
    return job["company"], job["title"]


def state_of(self, job_id: str) -> JobState:
    row = self.conn.execute("SELECT state FROM status WHERE job_id = ?", (job_id,)).fetchone()
    return row["state"] if row else "new"


def saved_and_applied(self) -> list[tuple[DigestRow, str]]:
    rows = self.conn.execute(
        _ROWS + " WHERE st.state IN ('saved', 'applied')"
        f" ORDER BY st.state DESC, {_DEADLINE} IS NULL, {_DEADLINE}, j.num"
    ).fetchall()
    return [(_row(r), r["state"]) for r in rows]


# --- alerts --------------------------------------------------------------------


def urgent_candidates(self, today: date, min_fit: int, within_days: int) -> list[DigestRow]:
    until = today + timedelta(days=within_days)
    rows = self.conn.execute(
        _ROWS + f" WHERE s.fit >= ? AND {_DEADLINE} BETWEEN ? AND ?"
        " AND COALESCE(st.state, 'new') IN ('new', 'saved')"
        " AND NOT EXISTS (SELECT 1 FROM alerts a"
        "                 WHERE a.job_id = j.job_id AND a.kind = 'urgent')"
        f" ORDER BY {_DEADLINE}, j.num",
        (min_fit, today.isoformat(), until.isoformat()),
    ).fetchall()
    return [_row(r) for r in rows]


def reminder_candidates(self, today: date, days_before: int) -> list[DigestRow]:
    until = today + timedelta(days=days_before)
    rows = self.conn.execute(
        _ROWS + f" WHERE st.state = 'saved' AND {_DEADLINE} BETWEEN ? AND ?"
        " AND NOT EXISTS (SELECT 1 FROM alerts a"
        "                 WHERE a.job_id = j.job_id AND a.kind = 'reminder')"
        f" ORDER BY {_DEADLINE}, j.num",
        (today.isoformat(), until.isoformat()),
    ).fetchall()
    return [_row(r) for r in rows]


def record_alert(self, job_id: str, kind: str, now: datetime) -> None:
    with self.conn:
        self.conn.execute(
            "INSERT OR IGNORE INTO alerts (job_id, kind, sent_at) VALUES (?, ?, ?)",
            (job_id, kind, now.isoformat()),
        )


# --- telegram ------------------------------------------------------------------


def telegram_offset(self) -> int | None:
    row = self.conn.execute("SELECT update_id FROM telegram_offset WHERE id = 1").fetchone()
    return row["update_id"] if row else None


def set_telegram_offset(self, update_id: int) -> None:
    with self.conn:
        self.conn.execute(
            "INSERT INTO telegram_offset (id, update_id) VALUES (1, ?)"
            " ON CONFLICT(id) DO UPDATE SET update_id = excluded.update_id",
            (update_id,),
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: store digests, job status, alerts and telegram offset

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Chunk 3: Sources

### Task 7: Greenhouse, Lever and Ashby feeds

**Files:**
- Create: `src/jobscout/sources/ats.py`, `tests/fixtures/greenhouse.json`, `tests/fixtures/lever.json`, `tests/fixtures/ashby.json`
- Test: `tests/test_ats.py`

- [ ] **Step 1: Write fixtures** (trimmed shapes of the real public responses)

`tests/fixtures/greenhouse.json`:
```json
{
  "jobs": [
    {
      "id": 8068011,
      "title": "Analyst, Financial Advisory (Entry-Level, New York and San Francisco)",
      "absolute_url": "https://job-boards.greenhouse.io/iconiq/jobs/8068011",
      "location": {"name": "San Francisco, CA; New York, NY"},
      "updated_at": "2026-09-20T12:00:00-04:00",
      "content": "&lt;p&gt;Designed for students graduating in &lt;b&gt;Spring 2027&lt;/b&gt;.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Asset allocation&lt;/li&gt;&lt;li&gt;Equity &amp;amp; option trading&lt;/li&gt;&lt;/ul&gt;"
    }
  ]
}
```

`tests/fixtures/lever.json`:
```json
[
  {
    "id": "7ea1a344-83a9-404b-b711-77f202e37b47",
    "text": "Summer 2027 Portfolio Management Analyst",
    "hostedUrl": "https://jobs.lever.co/harrisonst/7ea1a344-83a9-404b-b711-77f202e37b47",
    "categories": {"location": "Chicago, IL", "commitment": "Full-time"},
    "createdAt": 1758000000000,
    "descriptionPlain": "The program begins in early June 2027.",
    "lists": [
      {"text": "Responsibilities", "content": "<li>Update fund cash-flow models</li><li>Track fund performance</li>"}
    ],
    "additionalPlain": "Excel and financial modeling preferred."
  }
]
```

`tests/fixtures/ashby.json`:
```json
{
  "jobs": [
    {
      "id": "a1b2c3",
      "title": "Strategic Finance Analyst",
      "location": "Menlo Park, CA",
      "jobUrl": "https://jobs.ashbyhq.com/example/a1b2c3",
      "descriptionPlain": "Build models that shape pricing.",
      "publishedAt": "2026-09-10T00:00:00.000Z",
      "isListed": true
    },
    {
      "id": "hidden",
      "title": "Unlisted Role",
      "location": "Menlo Park, CA",
      "jobUrl": "https://jobs.ashbyhq.com/example/hidden",
      "descriptionPlain": "",
      "isListed": false
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_ats.py`:
```python
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
    raw = "&lt;p&gt;One &amp;amp; two&lt;/p&gt;&lt;ul&gt;&lt;li&gt;A&lt;/li&gt;&lt;li&gt;B&lt;/li&gt;&lt;/ul&gt;"
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
    with httpx.Client() as client:
        [p] = fetch_company(
            client, Company(name="Harrison Street", ats="lever", token="harrisonst")
        )
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
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_ats.py -v`
Expected: FAIL, `No module named 'jobscout.sources.ats'`

- [ ] **Step 4: Implement `src/jobscout/sources/ats.py`**

```python
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
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_ats.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: greenhouse, lever and ashby job-board sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Handshake alert emails via Gmail

Handshake's exact email markup is not known yet. This task builds a parser against a representative fixture, then Task 17 captures a real alert and adjusts the parser if needed.

**Files:**
- Create: `src/jobscout/sources/handshake_mail.py`, `tests/fixtures/handshake_alert.html`
- Test: `tests/test_handshake_mail.py`

- [ ] **Step 1: Write the fixture**

`tests/fixtures/handshake_alert.html`:
```html
<html><body>
<p>New jobs matching your saved search</p>
<table>
<tr><td><a href="https://app.joinhandshake.com/jobs/10861709?utm_source=email"><img src="logo.png"></a></td>
<td><a href="https://app.joinhandshake.com/jobs/10861709?utm_source=email">Fund Placement Analyst</a><br>M2O Private Fund Advisors<br>White Plains, NY</td></tr>
<tr><td><a href="https://app.joinhandshake.com/jobs/10999999">Analytics &amp; Sales Program</a><br>Bloomberg<br>New York, NY</td></tr>
<tr><td><a href="https://app.joinhandshake.com/jobs/10999999">View job</a></td></tr>
<tr><td><a href="https://app.joinhandshake.com/stu/postings">View all jobs</a></td></tr>
</table>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_handshake_mail.py`:
```python
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
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_handshake_mail.py -v`
Expected: FAIL, module not found

- [ ] **Step 4: Implement `src/jobscout/sources/handshake_mail.py`**

```python
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
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_handshake_mail.py -v`
Expected: 4 passed, 1 skipped (real fixture not captured yet)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: handshake alert emails via gmail read-only api

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Chunk 4: Scoring and messaging

### Task 9: Claude scorer

**Files:**
- Create: `src/jobscout/score.py`
- Test: `tests/test_score.py`, `tests/test_live_score.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_score.py`:
```python
from datetime import date
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from helpers import make_posting

from jobscout.config import Profile
from jobscout.score import ClaudeScorer, ScoreError, ScoreOut, to_score

PROFILE = Profile(available_from=date(2027, 6, 1), targets=["investment analyst"])


class FakeMessages:
    def __init__(self, out=None, exc=None, stop_reason="end_turn"):
        self.out, self.exc, self.stop_reason = out, exc, stop_reason
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.out)


def scorer_with(messages):
    return ClaudeScorer(client=SimpleNamespace(messages=messages), model="test-model")


def out(**kw):
    fields = {"fit": 8, "timing": "fits_june_2027", "deadline": "2026-10-30", "reason": "Good fit"}
    fields.update(kw)
    return ScoreOut(**fields)


def test_to_score_parses_deadline():
    assert to_score(out()).deadline == date(2026, 10, 30)
    assert to_score(out(deadline="Oct 30")).deadline is None
    assert to_score(out(deadline=None)).deadline is None


def test_to_score_caps_needs_start_now():
    assert to_score(out(fit=9, timing="needs_start_now")).fit == 5
    assert to_score(out(fit=3, timing="needs_start_now")).fit == 3


def test_to_score_clamps_and_truncates():
    assert to_score(out(fit=14)).fit == 10
    assert to_score(out(fit=0)).fit == 1
    long = to_score(out(reason="word " * 60))
    assert len(long.reason) <= 140
    assert long.reason.endswith("…")


def test_score_sends_profile_resume_and_posting():
    messages = FakeMessages(out=out())
    score = scorer_with(messages).score(make_posting(title="Unique Title"), PROFILE, "RESUME TEXT")
    assert score.fit == 8
    call = messages.calls[0]
    assert call["model"] == "test-model"
    assert call["output_format"] is ScoreOut
    system_text = " ".join(block["text"] for block in call["system"])
    assert "RESUME TEXT" in system_text and "2027-06-01" in system_text
    assert "Unique Title" in call["messages"][0]["content"]


def test_api_error_raises_score_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    messages = FakeMessages(exc=anthropic.APIConnectionError(request=request))
    with pytest.raises(ScoreError):
        scorer_with(messages).score(make_posting(), PROFILE, "resume")


def test_bad_stop_reason_raises():
    with pytest.raises(ScoreError, match="max_tokens"):
        scorer_with(FakeMessages(out=out(), stop_reason="max_tokens")).score(
            make_posting(), PROFILE, "resume"
        )


def test_missing_output_raises():
    with pytest.raises(ScoreError):
        scorer_with(FakeMessages(out=None)).score(make_posting(), PROFILE, "resume")
```

`tests/test_live_score.py`:
```python
"""Real Claude call. Run with: uv run pytest -m live"""

import os
from datetime import date

import pytest
from helpers import make_posting

from jobscout.config import Profile, Settings
from jobscout.score import ClaudeScorer, make_client

pytestmark = pytest.mark.live


def test_live_score():
    settings = Settings()
    if not (settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("no ANTHROPIC_API_KEY")
    scorer = ClaudeScorer(
        make_client(settings.anthropic_api_key, settings.anthropic_workspace_id),
        settings.anthropic_model,
    )
    posting = make_posting(
        title="Analyst, Financial Advisory (Entry-Level)",
        description="For students graduating Spring 2027; start Summer 2027. "
        "Asset allocation, portfolio reports, equity and option trading.",
    )
    profile = Profile(available_from=date(2027, 6, 1), targets=["investment analyst"])
    score = scorer.score(posting, profile, "MSc Finance 2027. Python options analytics.")
    assert score.fit >= 6
    assert score.timing == "fits_june_2027"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_score.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/score.py`**

```python
"""Claude scores a posting against the candidate profile and resume."""

from __future__ import annotations

from datetime import date

import anthropic
import pydantic
from pydantic import BaseModel

from jobscout.config import Profile
from jobscout.models import Posting, Score, Timing

MAX_TOKENS = 2000
NOT_NOW_CAP = 5
MAX_REASON = 140

SYSTEM_PROMPT = """You screen job postings for one candidate and score how well each fits.

fit, 1 to 10:
- 9-10: entry-level role squarely in the candidate's targets; start date works; skills match closely.
- 6-8: worth applying to; some gaps, or less central to the targets.
- 3-5: weak: wrong function, experience bar likely too high, or poor skills match.
- 1-2: clearly not a fit.

timing:
- "fits_june_2027": a 2027 program or summer-2027 start, or no start date stated and the role \
plausibly accepts someone available from the candidate's start date.
- "needs_start_now": clearly wants someone now or in 2026.
- "unclear": otherwise.

deadline: the application deadline as YYYY-MM-DD only if the posting states one, else null.
reason: one plain sentence under 140 characters giving the single most important reason for the \
score. No preamble."""


class ScoreOut(BaseModel):
    """What Claude returns; loosely typed so small slips don't fail validation."""

    fit: int
    timing: Timing
    deadline: str | None
    reason: str


class ScoreError(Exception):
    """Scoring failed; the posting stays unscored and is retried next run."""


def to_score(out: ScoreOut) -> Score:
    fit = max(1, min(10, out.fit))
    if out.timing == "needs_start_now":
        fit = min(fit, NOT_NOW_CAP)
    deadline = None
    if out.deadline:
        try:
            deadline = date.fromisoformat(out.deadline)
        except ValueError:
            deadline = None
    reason = " ".join(out.reason.split())
    if len(reason) > MAX_REASON:
        reason = reason[: MAX_REASON - 1].rstrip() + "…"
    return Score(fit=fit, timing=out.timing, deadline=deadline, reason=reason)


def candidate_block(profile: Profile, resume: str) -> str:
    return "\n".join(
        [
            "## Candidate",
            f"Available to start: {profile.available_from.isoformat()}",
            f"Work country: {profile.country}",
            f"Most years of experience they can claim: {profile.max_years_required}",
            f"Target roles: {'; '.join(profile.targets)}",
            profile.summary,
            "",
            "## Resume",
            resume.strip(),
        ]
    )


def posting_block(p: Posting) -> str:
    return "\n".join(
        [
            "## Posting",
            f"Company: {p.company}",
            f"Title: {p.title}",
            f"Location: {p.location or 'not stated'}",
            f"Deadline field: {p.deadline.isoformat() if p.deadline else 'none'}",
            "",
            p.description or "(No description available; judge from the title and company.)",
        ]
    )


def make_client(api_key: str, workspace_id: str = "") -> anthropic.Anthropic:
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")
    kwargs: dict[str, object] = {"api_key": api_key}
    if workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": workspace_id}
    return anthropic.Anthropic(**kwargs)


class ClaudeScorer:
    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        self._client = client
        self.model = model

    def score(self, posting: Posting, profile: Profile, resume: str) -> Score:
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT},
                    {
                        "type": "text",
                        "text": candidate_block(profile, resume),
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
                messages=[{"role": "user", "content": posting_block(posting)}],
                output_format=ScoreOut,
            )
        except (anthropic.APIError, pydantic.ValidationError) as exc:
            raise ScoreError(f"scoring call failed: {exc}") from exc
        if response.stop_reason != "end_turn":
            raise ScoreError(f"unexpected stop_reason={response.stop_reason}")
        if response.parsed_output is None:
            raise ScoreError("response had no parsed output")
        return to_score(response.parsed_output)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_score.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: claude scorer with timing cap and retries surfaced as ScoreError

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Message formatting

**Files:**
- Create: `src/jobscout/digest.py`
- Test: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_digest.py`:
```python
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
        'Summer 2027 start; options trading in role · <a href="https://example.com/a?b=1&amp;c=2">link</a>'
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_digest.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/digest.py`**

```python
"""Telegram message text (HTML parse mode). Pure functions, kept deliberately compact."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape

from jobscout.models import DigestRow

HINT = "Reply /save N, /applied N or /skip N"


def _closes(deadline: date | None) -> str:
    return f" · closes {deadline.strftime('%b')} {deadline.day}" if deadline else ""


def format_row(row: DigestRow) -> str:
    head = (
        f"#{row.num} <b>{escape(row.company)}</b>, {escape(row.title)}"
        f" · {row.fit}/10{_closes(row.deadline)}"
    )
    link = f'<a href="{escape(row.url, quote=True)}">link</a>'
    return f"{head}\n{escape(row.reason)} · {link}"


def format_digest(
    rows: Sequence[DigestRow],
    below: int,
    failed_scores: int,
    failed_sources: Sequence[str],
    min_fit: int,
) -> str:
    parts = ["<b>Jobs this week</b>"]
    if rows:
        parts.append("\n\n".join(format_row(r) for r in rows))
    else:
        parts.append("No new matches this week.")
    footer = []
    if below:
        footer.append(f"{below} more below {min_fit}")
    if failed_scores:
        footer.append(f"{failed_scores} couldn't be scored")
    if failed_sources:
        footer.append(f"failed: {', '.join(escape(s) for s in failed_sources)}")
    tail = [" · ".join(footer)] if footer else []
    if rows:
        tail.append(HINT)
    if tail:
        parts.append("\n".join(tail))
    return "\n\n".join(parts)


def format_urgent(row: DigestRow) -> str:
    return f"<b>Closes soon</b>\n{format_row(row)}"


def format_reminder(row: DigestRow, today: date) -> str:
    days = (row.deadline - today).days if row.deadline else 0
    when = {0: "today", 1: "tomorrow"}.get(days, f"in {days} days")
    return f"<b>Saved job closes {when}</b>\n{format_row(row)}"


def format_list(items: Sequence[tuple[DigestRow, str]]) -> str:
    if not items:
        return "Nothing saved or applied yet."
    sections = []
    for state, heading in (("saved", "Saved"), ("applied", "Applied")):
        lines = [
            f"#{row.num} {escape(row.company)}, {escape(row.title)}{_closes(row.deadline)}"
            for row, s in items
            if s == state
        ]
        if lines:
            sections.append(f"<b>{heading}</b>\n" + "\n".join(lines))
    return "\n\n".join(sections)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_digest.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: compact telegram message formatting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Telegram client

**Files:**
- Create: `src/jobscout/telegram.py` (copied from WheelTracker, plus `get_updates`)
- Test: `tests/test_telegram.py`

- [ ] **Step 1: Copy the sender**

Run: `cp ../WheelTracker/src/wheel_tracker/news/telegram.py src/jobscout/telegram.py`

It provides `TELEGRAM_LIMIT`, `TelegramError`, `visible_len`, `split_message`, `send_message(token, chat_id, text, timeout=10.0)`. Do not change it.

- [ ] **Step 2: Write the failing tests**

`tests/test_telegram.py`:
```python
import httpx
import pytest

from jobscout.telegram import TelegramError, get_updates, send_message

TOKEN = "123:abc"


def test_get_updates_passes_offset(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]', "offset": 42},
        ),
        json={"ok": True, "result": [{"update_id": 42, "message": {"text": "/list"}}]},
    )
    assert get_updates(TOKEN, 42) == [{"update_id": 42, "message": {"text": "/list"}}]


def test_get_updates_without_offset(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]'},
        ),
        json={"ok": True, "result": []},
    )
    assert get_updates(TOKEN, None) == []


def test_get_updates_error(httpx_mock):
    httpx_mock.add_response(json={"ok": False, "description": "Conflict"})
    with pytest.raises(TelegramError, match="Conflict"):
        get_updates(TOKEN, None)


def test_send_message_posts_html(httpx_mock):
    httpx_mock.add_response(json={"ok": True, "result": {}})
    send_message(TOKEN, "99", "<b>hi</b>")
    body = httpx_mock.get_requests()[0].read()
    assert b'"parse_mode":"HTML"' in body.replace(b" ", b"")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: FAIL, `cannot import name 'get_updates'`

- [ ] **Step 4: Append `get_updates` to `src/jobscout/telegram.py`**

```python
def get_updates(token: str, offset: int | None, timeout: float = 10.0) -> list[dict]:
    """New messages sent to the bot since `offset` (no long polling). Raises TelegramError."""
    params: dict[str, object] = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = httpx.get(f"{_API}/bot{token}/getUpdates", params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        raise TelegramError(str(exc)) from exc
    try:
        body = resp.json()
    except ValueError as exc:
        raise TelegramError(f"non-JSON response: {resp.text[:200]}") from exc
    if not body.get("ok"):
        raise TelegramError(str(body.get("description", f"HTTP {resp.status_code}")))
    return body.get("result", [])
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: telegram sender (from wheeltracker) plus getUpdates polling

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: Commands

**Files:**
- Create: `src/jobscout/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_commands.py`:
```python
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
    assert (
        handle(store, f"/applied {n}", NOW) == f"#{n} ICONIQ, Analyst, Financial Advisory: applied"
    )
    assert store.state_of(p.job_id) == "applied"


def test_handle_errors(store):
    assert handle(store, "/save 999", NOW) == "No job #999."
    assert handle(store, "/save", NOW) == "Usage: /save N"
    assert handle(store, "/delete 1", NOW) == HELP


def test_handle_list(store):
    p = add_scored(store, NOW, fit=9)
    handle(store, f"/save {num_of(store, p)}", NOW)
    assert handle(store, "/list", NOW).startswith("<b>Saved</b>")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_commands.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/commands.py`**

```python
"""Telegram replies: /save N, /applied N, /skip N, /list."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape

from jobscout.digest import format_list
from jobscout.store import Store

HELP = "Commands: /save N, /applied N, /skip N, /list"
_STATES = {"save": "saved", "applied": "applied", "skip": "skipped"}
_COMMAND = re.compile(r"^/(save|applied|skip|list)(?:@\w+)?(?:\s+#?(\d+))?\s*$", re.I)


@dataclass(frozen=True)
class Command:
    name: str
    num: int | None


def parse_command(text: str) -> Command | None:
    m = _COMMAND.match(text.strip())
    if not m:
        return None
    return Command(m.group(1).lower(), int(m.group(2)) if m.group(2) else None)


def handle(store: Store, text: str, now: datetime) -> str:
    """Apply one command and return the reply text."""
    cmd = parse_command(text)
    if cmd is None:
        return HELP
    if cmd.name == "list":
        return format_list(store.saved_and_applied())
    if cmd.num is None:
        return f"Usage: /{cmd.name} N"
    state = _STATES[cmd.name]
    job = store.set_status(cmd.num, state, now)
    if job is None:
        return f"No job #{cmd.num}."
    company, title = job
    return f"#{cmd.num} {escape(company)}, {escape(title)}: {state}"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_commands.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: telegram status commands

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Urgent pings and reminders

**Files:**
- Create: `src/jobscout/alerts.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_alerts.py`:
```python
from datetime import UTC, date, datetime

import pytest
from helpers import NOW, add_scored, num_of

from jobscout.alerts import is_quiet, send_alerts
from jobscout.telegram import TelegramError


@pytest.mark.parametrize(
    ("utc_hour", "utc_minute", "quiet"),
    [(22, 30, True), (6, 59, True), (7, 0, False), (21, 59, False)],  # Lisbon = UTC+1 in Sept
)
def test_is_quiet(utc_hour, utc_minute, quiet):
    assert is_quiet(datetime(2026, 9, 27, utc_hour, utc_minute, tzinfo=UTC)) is quiet


def test_urgent_sent_once(store):
    add_scored(store, NOW, fit=8, deadline=date(2026, 10, 2))
    sent = []
    assert send_alerts(store, sent.append, NOW) == 1
    assert sent[0].startswith("<b>Closes soon</b>")
    assert send_alerts(store, sent.append, NOW) == 0


def test_nothing_during_quiet_hours(store):
    add_scored(store, NOW, fit=8, deadline=date(2026, 10, 2))
    sent = []
    assert send_alerts(store, sent.append, datetime(2026, 9, 27, 23, 0, tzinfo=UTC)) == 0
    assert sent == []
    assert send_alerts(store, sent.append, NOW) == 1  # still pending, sent after quiet hours


def test_reminder_for_saved_job(store):
    p = add_scored(store, NOW, fit=6, deadline=date(2026, 9, 30))
    store.set_status(num_of(store, p), "saved", NOW)
    sent = []
    send_alerts(store, sent.append, NOW)
    assert len(sent) == 1
    assert "Saved job closes in 3 days" in sent[0]


def test_telegram_failure_leaves_alert_pending(store):
    add_scored(store, NOW, fit=9, deadline=date(2026, 10, 1))

    def broken(_text):
        raise TelegramError("down")

    assert send_alerts(store, broken, NOW) == 0
    sent = []
    assert send_alerts(store, sent.append, NOW) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/alerts.py`**

```python
"""Urgent pings (strong match closing soon) and reminders for saved jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time
from zoneinfo import ZoneInfo

from jobscout.digest import format_reminder, format_urgent
from jobscout.store import Store
from jobscout.telegram import TelegramError

log = logging.getLogger(__name__)

LISBON = ZoneInfo("Europe/Lisbon")
QUIET_START = time(23, 0)
QUIET_END = time(8, 0)
URGENT_FIT = 8
URGENT_DAYS = 7
REMINDER_DAYS = 3


def is_quiet(now: datetime) -> bool:
    local = now.astimezone(LISBON).time()
    return local >= QUIET_START or local < QUIET_END


def send_alerts(store: Store, send: Callable[[str], None], now: datetime) -> int:
    """Send pending pings and reminders. Returns how many were sent.

    An alert is recorded only after Telegram accepts it, so a failure or quiet
    hours leave it pending for the next run.
    """
    if is_quiet(now):
        return 0
    today = now.astimezone(LISBON).date()
    pending = [
        (row, "urgent", format_urgent(row))
        for row in store.urgent_candidates(today, URGENT_FIT, URGENT_DAYS)
    ] + [
        (row, "reminder", format_reminder(row, today))
        for row in store.reminder_candidates(today, REMINDER_DAYS)
    ]
    sent = 0
    for row, kind, text in pending:
        try:
            send(text)
        except TelegramError as exc:
            log.warning("alert not sent, will retry: %s", exc)
            break
        store.record_alert(row.job_id, kind, now)
        sent += 1
    return sent
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: urgent pings and saved-job reminders with quiet hours

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Chunk 5: Runs and setup

### Task 14: Run lock

**Files:**
- Create: `src/jobscout/lock.py`
- Test: `tests/test_lock.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_lock.py`:
```python
import os
import time

import pytest

from jobscout.lock import LockBusy, file_lock


def test_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "x.lock"
    with file_lock(path):
        assert path.exists()
        with pytest.raises(LockBusy), file_lock(path):
            pass
    assert not path.exists()


def test_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / "x.lock"
    path.write_text("123")
    old = time.time() - 3 * 3600
    os.utime(path, (old, old))
    with file_lock(path):
        assert path.read_text() == str(os.getpid())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_lock.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/lock.py`**

```python
"""A lock file so the hourly and weekly runs never overlap."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path("jobscout.lock")
STALE_SECONDS = 2 * 3600


class LockBusy(Exception):
    """Another run holds the lock."""


def _create(path: Path) -> int:
    return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


@contextmanager
def file_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    try:
        fd = _create(path)
    except FileExistsError:
        if time.time() - path.stat().st_mtime < STALE_SECONDS:
            raise LockBusy(str(path)) from None
        path.unlink(missing_ok=True)  # left behind by a crashed run
        fd = _create(path)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_lock.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: run lock file

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: Weekly run

**Files:**
- Create: `src/jobscout/weekly.py`
- Test: `tests/test_weekly.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_weekly.py`:
```python
from datetime import date, timedelta

from helpers import NOW, make_posting

from jobscout.config import Profile
from jobscout.models import Score
from jobscout.score import ScoreError
from jobscout.sources.ats import SourceError
from jobscout.telegram import TelegramError
from jobscout.weekly import Source, run_weekly

PROFILE = Profile(available_from=date(2027, 6, 1))

GOOD = make_posting(source_id="good", title="Investment Analyst")
OK = make_posting(source_id="ok", title="Financial Analyst I")
WEAK = make_posting(source_id="weak", title="Accounts Payable Clerk")
SENIOR = make_posting(source_id="senior", title="Senior Portfolio Manager")
BROKEN = make_posting(source_id="broken", title="Markets Analyst")

FITS = {"good": 9, "ok": 6, "weak": 3}


def fake_scorer(calls):
    def score(p):
        calls.append(p.source_id)
        if p.source_id == "broken":
            raise ScoreError("boom")
        return Score(fit=FITS[p.source_id], timing="fits_june_2027", reason="r")

    return score


def failing_source():
    raise SourceError("down")


def run(store, sent, calls, now=NOW, sources=None):
    sources = sources or [
        Source("Board", lambda: [GOOD, OK, WEAK, SENIOR, BROKEN]),
        Source("Harrison Street (lever)", failing_source),
    ]
    run_weekly(store, sources, fake_scorer(calls), "m", PROFILE, sent.append, now)


def test_weekly_digest(store):
    sent, calls = [], []
    run(store, sent, calls)
    assert sorted(calls) == ["broken", "good", "ok", "weak"]  # senior filtered by rules
    [digest] = sent
    assert digest.index("Investment Analyst") < digest.index("Financial Analyst I")
    assert "Accounts Payable" not in digest
    assert "couldn't be scored" not in digest  # broken has failed once; retried next week
    assert "1 more below 6" in digest
    assert "failed: Harrison Street (lever)" in digest
    assert store.unsent_digests() == []


def test_second_week_does_not_repeat_or_rescore(store):
    sent, calls = [], []
    run(store, sent, calls)
    sent2, calls2 = [], []
    run(store, sent2, calls2, now=NOW + timedelta(days=7))
    assert calls2 == ["broken"]  # only the failed one is retried
    assert "No new matches this week." in sent2[0]
    assert "more below" not in sent2[0]  # last week's weak job is not counted again


def test_unsent_digest_is_kept_when_telegram_fails(store):
    def broken_send(_text):
        raise TelegramError("down")

    run_weekly(
        store, [Source("Board", lambda: [GOOD])], fake_scorer([]), "m", PROFILE, broken_send, NOW
    )
    assert len(store.unsent_digests()) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_weekly.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/weekly.py`**

```python
"""Weekly run: fetch, filter, score, send the digest.

Run: uv run python -m jobscout.weekly
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx

from jobscout.alerts import LISBON, send_alerts
from jobscout.config import Profile, Settings, Watchlist, load_watchlist
from jobscout.digest import format_digest
from jobscout.filter import apply_rules
from jobscout.lock import LockBusy, file_lock
from jobscout.models import Posting, Score
from jobscout.score import ClaudeScorer, ScoreError, make_client
from jobscout.sources.ats import USER_AGENT, SourceError, fetch_company
from jobscout.sources.handshake_mail import fetch_handshake
from jobscout.store import Store
from jobscout.telegram import TelegramError, send_message

log = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MIN_FIT = 6
DIGEST_SIZE = 8
FRESH_DAYS = 8


@dataclass(frozen=True)
class Source:
    name: str
    fetch: Callable[[], list[Posting]]
    allow_non_us: bool = False


def run_weekly(
    store: Store,
    sources: list[Source],
    score: Callable[[Posting], Score],
    model: str,
    profile: Profile,
    send: Callable[[str], None],
    now: datetime,
) -> None:
    failed: list[str] = []
    for source in sources:
        try:
            postings = source.fetch()
        except SourceError as exc:
            log.warning("source %s failed: %s", source.name, exc)
            failed.append(source.name)
            continue
        log.info("source %s: %d postings", source.name, len(postings))
        for p in postings:
            store.upsert_posting(p, now)
            store.record_rule(p.job_id, apply_rules(p, profile, source.allow_non_us), now)

    since = now - timedelta(days=FRESH_DAYS)
    for p in store.jobs_to_score(since):
        try:
            result = score(p)
        except ScoreError as exc:
            log.warning("scoring %s failed: %s", p.job_id, exc)
            store.record_score_failure(p.job_id, p.content_hash, now)
            continue
        store.save_score(p.job_id, p.content_hash, result, model, now)

    today = now.astimezone(LISBON).date()
    rows = store.digest_candidates(MIN_FIT, since, today, DIGEST_SIZE)
    body = format_digest(
        rows,
        below=store.count_below(MIN_FIT, store.last_digest_at() or since),
        failed_scores=store.count_score_failed(since),
        failed_sources=failed,
        min_fit=MIN_FIT,
    )
    digest_id = store.create_digest(body, [r.job_id for r in rows], now)
    try:
        send(body)
    except TelegramError as exc:
        log.warning("digest not sent, hourly run will retry: %s", exc)
    else:
        store.mark_digest_sent(digest_id, now)
    send_alerts(store, send, now)


def build_sources(client: httpx.Client, settings: Settings, watchlist: Watchlist) -> list[Source]:
    sources = [
        Source(f"{c.name} ({c.ats})", partial(fetch_company, client, c), c.allow_non_us)
        for c in watchlist.company
    ]
    if settings.handshake_enabled:
        sources.append(Source("Handshake", partial(fetch_handshake, client, settings)))
    return sources


def main() -> int:
    logging.basicConfig(filename="jobscout.log", level=logging.INFO, format=LOG_FORMAT)
    try:
        with file_lock():
            settings = Settings()
            watchlist = load_watchlist(settings.watchlist_path)
            resume = settings.resume_path.read_text(encoding="utf-8")
            scorer = ClaudeScorer(
                make_client(settings.anthropic_api_key, settings.anthropic_workspace_id),
                settings.anthropic_model,
            )
            store = Store.open(settings.db_path)
            send = partial(send_message, settings.telegram_bot_token, settings.telegram_chat_id)
            with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
                run_weekly(
                    store,
                    build_sources(client, settings, watchlist),
                    lambda p: scorer.score(p, watchlist.profile, resume),
                    settings.anthropic_model,
                    watchlist.profile,
                    send,
                    datetime.now(UTC),
                )
    except LockBusy:
        log.info("another run holds the lock; skipping")
        return 0
    except Exception:
        log.exception("weekly run failed")
        return 1
    log.info("weekly run done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_weekly.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: weekly fetch-filter-score-digest run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 16: Hourly run

**Files:**
- Create: `src/jobscout/hourly.py`
- Test: `tests/test_hourly.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_hourly.py`:
```python
from datetime import UTC, date, datetime

from helpers import NOW, add_scored, num_of

from jobscout.hourly import run_hourly
from jobscout.telegram import TelegramError

CHAT = "99"


def update(update_id, text, chat=CHAT):
    return {"update_id": update_id, "message": {"chat": {"id": int(chat)}, "text": text}}


def test_commands_from_owner_only(store):
    p = add_scored(store, NOW, fit=7)
    n = num_of(store, p)
    updates = [update(10, f"/applied {n}"), update(11, f"/skip {n}", chat="5"), update(12, "hi")]
    offsets, sent = [], []

    def fetch(offset):
        offsets.append(offset)
        return updates

    run_hourly(store, fetch, sent.append, CHAT, NOW)
    assert offsets == [None]
    assert store.state_of(p.job_id) == "applied"  # the other chat's /skip was ignored
    assert sent == [f"#{n} ICONIQ, Analyst, Financial Advisory: applied"]  # plain text ignored
    assert store.telegram_offset() == 13


def test_resends_unsent_digest_and_sends_alerts(store):
    store.create_digest("old digest", [], NOW)
    add_scored(store, NOW, fit=9, deadline=date(2026, 10, 1))
    sent = []
    run_hourly(store, lambda _o: [], sent.append, CHAT, NOW)
    assert sent[0] == "old digest"
    assert sent[1].startswith("<b>Closes soon</b>")
    assert store.unsent_digests() == []


def test_quiet_hours_still_answer_commands(store):
    night = datetime(2026, 9, 27, 23, 30, tzinfo=UTC)
    add_scored(store, NOW, fit=9, deadline=date(2026, 10, 1))
    sent = []
    run_hourly(store, lambda _o: [update(1, "/list")], sent.append, CHAT, night)
    assert sent == ["Nothing saved or applied yet."]


def test_telegram_down_is_not_fatal(store):
    def fetch(_offset):
        raise TelegramError("down")

    run_hourly(store, fetch, lambda _t: None, CHAT, NOW)  # no exception
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_hourly.py -v`
Expected: FAIL, module not found

- [ ] **Step 3: Implement `src/jobscout/hourly.py`**

```python
"""Hourly run: answer commands, resend an unsent digest, send pings and reminders.

Run: uv run python -m jobscout.hourly
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

from jobscout.alerts import send_alerts
from jobscout.commands import handle
from jobscout.config import Settings
from jobscout.lock import LockBusy, file_lock
from jobscout.store import Store
from jobscout.telegram import TelegramError, get_updates, send_message
from jobscout.weekly import LOG_FORMAT

log = logging.getLogger(__name__)


def process_commands(
    store: Store, updates: list[dict], chat_id: str, reply: Callable[[str], None], now: datetime
) -> None:
    for u in updates:
        store.set_telegram_offset(u["update_id"] + 1)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id):
            continue
        text = msg.get("text") or ""
        if not text.startswith("/"):
            continue
        try:
            reply(handle(store, text, now))
        except TelegramError as exc:
            log.warning("reply not sent: %s", exc)


def resend_unsent(store: Store, send: Callable[[str], None], now: datetime) -> None:
    for digest_id, body in store.unsent_digests():
        try:
            send(body)
        except TelegramError as exc:
            log.warning("digest %s still unsent: %s", digest_id, exc)
            return
        store.mark_digest_sent(digest_id, now)


def run_hourly(
    store: Store,
    fetch_updates: Callable[[int | None], list[dict]],
    send: Callable[[str], None],
    chat_id: str,
    now: datetime,
) -> None:
    try:
        updates = fetch_updates(store.telegram_offset())
    except TelegramError as exc:
        log.warning("getUpdates failed: %s", exc)
        updates = []
    process_commands(store, updates, chat_id, send, now)
    resend_unsent(store, send, now)
    send_alerts(store, send, now)


def main() -> int:
    logging.basicConfig(filename="jobscout.log", level=logging.INFO, format=LOG_FORMAT)
    try:
        with file_lock():
            settings = Settings()
            run_hourly(
                Store.open(settings.db_path),
                partial(get_updates, settings.telegram_bot_token),
                partial(send_message, settings.telegram_bot_token, settings.telegram_chat_id),
                settings.telegram_chat_id,
                datetime.now(UTC),
            )
    except LockBusy:
        log.info("another run holds the lock; skipping")
        return 0
    except Exception:
        log.exception("hourly run failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: all pass, live test deselected, real-Handshake test skipped.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: hourly commands, digest resend and alerts run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 17: Watchlist checker, launchers, README and first live run

**Files:**
- Create: `src/jobscout/check.py`, `scripts/run_weekly.cmd`, `scripts/run_hourly.cmd`, `scripts/run_hidden.vbs`, `README.md`, `profile/resume.md` (gitignored)

- [ ] **Step 1: Write `src/jobscout/check.py`**

```python
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
```

- [ ] **Step 2: Launchers**

`scripts/run_weekly.cmd`:
```bat
@echo off
rem Task Scheduler launcher: fixes the working directory (so .env and the DB resolve)
rem and calls uv by full path, since scheduled tasks do not see the user's PATH.
cd /d "%~dp0.."
"%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe" run python -m jobscout.weekly
```

`scripts/run_hourly.cmd`: identical except the last line ends in `jobscout.hourly`.

`scripts/run_hidden.vbs`:
```vb
' Runs a launcher in this folder with no console window: wscript run_hidden.vbs run_weekly.cmd
' Window style 0 = hidden; True = wait so Task Scheduler sees the real exit.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
cmdPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), WScript.Arguments(0))
shell.Run """" & cmdPath & """", 0, True
```

- [ ] **Step 3: Write `README.md`**

````markdown
# JobScout

Weekly job finder: checks company job boards and Handshake alert emails, drops
obvious non-fits, has Claude score the rest against your profile, and sends a
compact Telegram digest. Strong matches closing within 7 days get an immediate
ping; saved jobs get a reminder 3 days before their deadline.

## Setup

1. `uv venv --python "C:/Users/quint/AppData/Local/Programs/Python/Python311/python.exe"` then `uv sync`.
2. Copy `.env.example` to `.env`.
3. **Telegram:** create a new bot with @BotFather (keep it separate from the
   WheelTracker news bot, since this one reads replies). Put its token in
   `TELEGRAM_BOT_TOKEN`, send the bot any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`
   into `TELEGRAM_CHAT_ID`.
4. **Claude:** set `ANTHROPIC_API_KEY`.
5. **Resume:** paste your resume text into `profile/resume.md` (gitignored).
6. **Watchlist:** edit `watchlist.toml`, then check tokens with
   `uv run python -m jobscout.check`.
7. **Handshake (optional):** in Handshake, save searches with email alerts on.
   In Google Cloud Console create a project, enable the Gmail API, configure the
   OAuth consent screen (External, add yourself as a test user), and create an
   OAuth client of type *Desktop app*. Download it as `credentials.json` into this
   folder, then run `uv run python -m jobscout.sources.handshake_mail auth`.
   Set `HANDSHAKE_ENABLED=false` to skip this source.

## Run

```
uv run python -m jobscout.weekly   # fetch, score, send digest
uv run python -m jobscout.hourly   # commands, resend, pings
```

Reply to the bot with `/save 12`, `/applied 12`, `/skip 12` or `/list`.

## Schedule (Windows Task Scheduler, times are this PC's local time)

```
schtasks /Create /TN "JobScout Weekly" /SC WEEKLY /D SUN /ST 18:00 /TR "wscript.exe \"C:\Users\quint\projects\JobScout\scripts\run_hidden.vbs\" run_weekly.cmd"
schtasks /Create /TN "JobScout Hourly" /SC HOURLY /ST 00:05 /TR "wscript.exe \"C:\Users\quint\projects\JobScout\scripts\run_hidden.vbs\" run_hourly.cmd"
```

Logs go to `jobscout.log`.
````

- [ ] **Step 4: Create `profile/resume.md`**

Extract the text of `C:\Users\quint\OneDrive\Career\Goodman_Quinten_Resume_2026.docx` into `profile/resume.md` (plain Markdown, one bullet per line). This file is gitignored.

- [ ] **Step 5: Lint and full test run**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest`
Expected: clean lint; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: watchlist checker, task scheduler launchers and readme

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Grow the watchlist (with the user)**

Try likely board tokens for the saved-jobs firms and keep the ones `jobscout.check` reports `ok` for. Candidates to try: Anduril (`greenhouse:andurilindustries`), Snowflake (`ashby:snowflake`, `greenhouse:snowflake`), Accuracy, Shea & Company, 747 Capital, Stormfield, Ridgepeak, M2O, Leargas (`lever:` / `greenhouse:` with the lowercased name). Firms on custom career sites (Bloomberg, HSBC, Nomura, FM, New York Life, Pokémon) are covered only through Handshake alerts. Commit `watchlist.toml`.

- [ ] **Step 8: First live run (user present)**

1. User fills `.env` (Telegram bot + chat id, Anthropic key).
2. `uv run pytest -m live` → live score test passes.
3. If Handshake is enabled: run `auth`, then `uv run python -m jobscout.sources.handshake_mail dump`, then `uv run pytest tests/test_handshake_mail.py -v`. If `test_parse_real_alert_if_captured` fails, adjust `_JOB_LINK` / `parse_alert` to the real markup (Handshake may use tracked redirect links; if so, match the tracked host and pull the job id from the redirect target), add a trimmed copy of the real structure to `tests/fixtures/handshake_alert.html`, and rerun until green. Commit the parser change (the real capture stays gitignored).
4. `uv run python -m jobscout.weekly` → digest arrives on Telegram; check `jobscout.log`.
5. Reply `/list` and `/save N` to the bot, run `uv run python -m jobscout.hourly`, confirm the replies.
6. Register both scheduled tasks with the `schtasks` commands in the README.
