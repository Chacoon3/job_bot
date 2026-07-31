from dataclasses import dataclass
from typing import get_args

import pytest

from job_bot.agent.dropdown_regulator import (
    get_dropdown_regulator_by_field_key,
    match_disability_option,
    match_disability_status_option,
    match_gender_option,
    match_race_ethnicity_option,
    match_regulated_option,
    match_veteran_option,
    match_veteran_status_option,
    match_yes_no_option,
    regulate_country,
    regulate_phone_country_code,
)
from job_bot.schemas import (
    DisabilityOption,
    DisabilityStatusOption,
    GenderOption,
    RaceEthnicityOption,
    VeteranOption,
    VeteranStatusOption,
    YesNoOption,
)


@dataclass(frozen=True)
class Option:
    label: str


def test_literal_types_enumerate_standard_options() -> None:
    assert get_args(YesNoOption) == ("yes", "no", "decline")
    assert get_args(VeteranOption) == ("yes", "no", "decline")
    assert get_args(DisabilityOption) == ("yes", "no", "decline")
    assert VeteranStatusOption is VeteranOption
    assert DisabilityStatusOption is DisabilityOption
    assert get_args(GenderOption) == (
        "male",
        "female",
        "nonbinary",
        "self_describe",
        "decline",
    )
    assert set(get_args(RaceEthnicityOption)) == {
        "american_indian_alaska_native",
        "asian",
        "black",
        "hispanic_latino",
        "native_hawaiian_pacific_islander",
        "white",
        "two_or_more",
        "other",
        "decline",
    }


@pytest.mark.parametrize(
    ("matcher", "requested", "label"),
    [
        (match_yes_no_option, "yes", "Yes, I agree"),
        (match_veteran_option, "no", "I am not a protected veteran"),
        (
            match_disability_option,
            "yes",
            "Yes, I have a disability or have had one in the past",
        ),
        (match_gender_option, "nonbinary", "Gender non-conforming"),
        (match_race_ethnicity_option, "two_or_more", "Mixed race"),
    ],
)
def test_matchers_resolve_standard_options(matcher, requested: str, label: str) -> None:
    expected = Option(label)

    assert matcher([Option("Unrelated"), expected], requested) is expected


def test_matcher_rejects_missing_option() -> None:
    with pytest.raises(LookupError, match="No option semantically matches"):
        match_gender_option([Option("Male"), Option("Female")], "nonbinary")


def test_matcher_rejects_ambiguous_option() -> None:
    with pytest.raises(ValueError, match="Multiple options semantically match"):
        match_gender_option([Option("Male"), Option("Man")], "male")


def test_status_qualified_matcher_aliases() -> None:
    veteran = Option("Protected veteran")
    disability = Option("No, I don't have a disability")

    assert match_veteran_status_option([veteran], "yes") is veteran
    assert match_disability_status_option([disability], "no") is disability


@pytest.mark.parametrize(
    "label",
    [
        "+1",
        "+1 US",
        "US (+1)",
        "U.S. +1",
        "United States +1",
        "United States of America (+1)",
    ],
)
def test_phone_country_regulator_matches_us_calling_code_labels(label: str) -> None:
    assert regulate_phone_country_code(label) == "United States"


@pytest.mark.parametrize(
    "label",
    ["+44", "+44 UK", "UK (+44)", "U.K. +44", "GB +44", "United Kingdom (+44)"],
)
def test_phone_country_regulator_matches_uk_calling_code_labels(label: str) -> None:
    assert regulate_phone_country_code(label) == "United Kingdom"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("US", "United States"),
        ("United States", "United States"),
        ("UK", "United Kingdom"),
        ("United Kingdom", "United Kingdom"),
        ("bosnia and herzegovina", "Bosnia and Herzegovina"),
        ("UNKNOWN COUNTRY", "Unknown Country"),
    ],
)
def test_phone_country_regulator_handles_country_only_labels(
    label: str,
    expected: str,
) -> None:
    assert regulate_phone_country_code(label) == expected


def test_phone_country_field_uses_phone_country_regulator() -> None:
    assert get_dropdown_regulator_by_field_key("phone_country") is regulate_phone_country_code


def test_phone_country_regulator_matches_code_to_abbreviated_dropdown_label() -> None:
    expected = Option("US (+1)")

    assert (
        match_regulated_option(
            [Option("UK (+44)"), expected],
            "+1",
            regulate_phone_country_code,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("usa", "United States"),
        ("U.S.A.", "United States"),
        ("UK", "United Kingdom"),
        ("u a e", "United Arab Emirates"),
        ("KOR", "South Korea"),
        ("bosnia AND herzegovina", "Bosnia and Herzegovina"),
        ("  NEW   ZEALAND  ", "New Zealand"),
    ],
)
def test_country_regulator_returns_full_title_case_name(label: str, expected: str) -> None:
    assert regulate_country(label) == expected


def test_country_regulator_matches_abbreviation_to_full_dropdown_label() -> None:
    expected = Option("United Arab Emirates")

    assert (
        match_regulated_option([Option("United States"), expected], "UAE", regulate_country)
        is expected
    )


def test_country_field_uses_country_regulator() -> None:
    assert get_dropdown_regulator_by_field_key("country") is regulate_country
