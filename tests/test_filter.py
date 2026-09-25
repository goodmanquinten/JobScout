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


@pytest.mark.parametrize(
    ("location", "non_us"),
    [("IN-Pune", True), ("GB-London", True), ("US-CA-Menlo Park", False), ("US-NY-Remote", False)],
)
def test_country_code_prefixed_locations(location, non_us):
    assert is_non_us(location) is non_us


def test_title_include_limits_big_employers():
    include = ["financ", "fp&a"]
    kept = apply_rules(make_posting(title="Financial Analyst I"), PROFILE, title_include=include)
    dropped = apply_rules(make_posting(title="Software Engineer"), PROFILE, title_include=include)
    assert kept.keep is True
    assert dropped.keep is False
    assert dropped.reason == "title outside company filter"
    assert apply_rules(make_posting(title="Software Engineer"), PROFILE).keep is True
