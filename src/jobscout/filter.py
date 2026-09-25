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
