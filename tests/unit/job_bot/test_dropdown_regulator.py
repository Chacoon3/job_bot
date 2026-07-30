from dataclasses import dataclass
from typing import get_args

import pytest

from job_bot.agent.dropdown_regulator import (
    DisabilityOption,
    DisabilityStatusOption,
    GenderOption,
    RaceEthnicityOption,
    VeteranOption,
    VeteranStatusOption,
    YesNoOption,
    match_disability_option,
    match_disability_status_option,
    match_gender_option,
    match_race_ethnicity_option,
    match_veteran_option,
    match_veteran_status_option,
    match_yes_no_option,
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
