"""Conservative canonicalizers for common job-application dropdowns.

A regulator is applied to both the requested label and every available label.
It translates known wording variants to the same semantic key and leaves
unknown wording as a normalized, namespaced value.  Unknown labels are never
guessed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar


class HasLabel(Protocol):
    label: str


OptionT = TypeVar("OptionT", bound=HasLabel)
Regulator = Callable[[str], str]

YesNoOption = Literal["yes", "no", "decline"]
VeteranOption = Literal["yes", "no", "decline"]
DisabilityOption = Literal["yes", "no", "decline"]
VeteranStatusOption = VeteranOption
DisabilityStatusOption = DisabilityOption
GenderOption = Literal["male", "female", "nonbinary", "self_describe", "decline"]
RaceEthnicityOption = Literal[
    "american_indian_alaska_native",
    "asian",
    "black",
    "hispanic_latino",
    "native_hawaiian_pacific_islander",
    "white",
    "two_or_more",
    "other",
    "decline",
]


def normalize_dropdown_label(label: str) -> str:
    """Normalize presentation differences while retaining semantic wording."""
    normalized = unicodedata.normalize("NFKC", label).casefold()
    normalized = normalized.replace("&", " and ")
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


@dataclass(frozen=True)
class _Rule:
    key: str
    patterns: tuple[re.Pattern[str], ...]


def _compile_rules(
    definitions: Mapping[str, Iterable[str]],
) -> tuple[_Rule, ...]:
    return tuple(
        _Rule(key, tuple(re.compile(pattern) for pattern in patterns))
        for key, patterns in definitions.items()
    )


def _regulate(label: str, rules: Sequence[_Rule]) -> str:
    normalized = normalize_dropdown_label(label)
    for rule in rules:
        if any(pattern.fullmatch(normalized) for pattern in rule.patterns):
            return rule.key

    # Namespace unmatched text so it cannot accidentally equal a semantic key.
    return f"raw:{normalized}"


_DECLINE = (
    r"(?:i )?(?:do not|don t|dont) (?:wish|want|choose) to "
    r"(?:answer|respond|disclose|identify|self identify)",
    r"(?:i )?prefer not to (?:answer|respond|disclose|identify|self identify|say)",
    r"(?:choose|chose|decline) not to (?:answer|respond|disclose|identify|self identify)",
    r"decline to (?:answer|respond|disclose|identify|self identify)",
    r"decline",
)


_YES_NO_RULES = _compile_rules(
    {
        "answer:decline": _DECLINE,
        "answer:yes": (
            r"yes",
            r"y",
            r"true",
            r"yes\b.*",
        ),
        "answer:no": (
            r"no",
            r"n",
            r"false",
            r"no\b.*",
        ),
    }
)


def regulate_yes_no(label: str) -> str:
    """Canonicalize ordinary yes/no/decline choices."""
    return _regulate(label, _YES_NO_RULES)


_VETERAN_RULES = _compile_rules(
    {
        "veteran:decline": _DECLINE,
        "veteran:no": (
            r"no",
            r"not a veteran",
            r"i am not a veteran",
            r"i am not a protected veteran",
            r"not a protected veteran",
            r"i do not identify as a protected veteran",
            r"i am not one of the following protected veterans",
            r"no\b.*(?:veteran|protected veteran).*",
        ),
        "veteran:yes": (
            r"yes",
            r"veteran",
            r"protected veteran",
            r"i am a veteran",
            r"i am a protected veteran",
            r"i identify as a protected veteran",
            r"i identify as one or more (?:of the )?classifications of protected veteran",
            r"one or more (?:of the )?classifications of protected veteran",
            r"yes\b.*(?:veteran|protected veteran).*",
        ),
    }
)


def regulate_veteran_status(label: str) -> str:
    """Canonicalize U.S. veteran self-identification choices."""
    return _regulate(label, _VETERAN_RULES)


_DISABILITY_RULES = _compile_rules(
    {
        "disability:decline": _DECLINE,
        "disability:no": (
            r"no",
            r"no i do not have a disability",
            r"no i don t have a disability",
            r"i do not have a disability",
            r"i don t have a disability",
            r"no\b.*(?:disability|disabled).*",
        ),
        "disability:yes": (
            r"yes",
            r"yes i have a disability",
            r"i have a disability",
            r"i have a disability or have had one in the past",
            r"yes i have a disability or have had one in the past",
            r"yes\b.*(?:disability|disabled).*",
        ),
    }
)


def regulate_disability_status(label: str) -> str:
    """Canonicalize voluntary disability self-identification choices."""
    return _regulate(label, _DISABILITY_RULES)


_GENDER_RULES = _compile_rules(
    {
        "gender:decline": _DECLINE,
        "gender:male": (
            r"male",
            r"man",
            r"cis male",
            r"cisgender male",
            r"i identify as (?:a )?(?:male|man)",
        ),
        "gender:female": (
            r"female",
            r"woman",
            r"cis female",
            r"cisgender female",
            r"i identify as (?:a )?(?:female|woman)",
        ),
        "gender:nonbinary": (
            r"non binary",
            r"nonbinary",
            r"gender non conforming",
            r"genderqueer",
        ),
        "gender:self_describe": (
            r"self describe",
            r"prefer to self describe",
            r"another gender identity",
            r"other",
        ),
    }
)


def regulate_gender(label: str) -> str:
    """Canonicalize common gender choices without inferring an identity."""
    return _regulate(label, _GENDER_RULES)


_RACE_RULES = _compile_rules(
    {
        "race:decline": _DECLINE,
        "race:two_or_more": (
            r"two or more races",
            r"multiracial",
            r"multi racial",
            r"mixed race",
        ),
        "race:hispanic_latino": (
            r"hispanic or latino",
            r"hispanic latino",
            r"latino or hispanic",
            r"latino",
            r"hispanic",
        ),
        "race:asian": (
            r"asian",
            r"asian not hispanic or latino",
        ),
        "race:white": (
            r"white",
            r"white not hispanic or latino",
            r"caucasian",
        ),
        "race:black": (
            r"black",
            r"african american",
            r"black or african american",
            r"black or african american not hispanic or latino",
        ),
        "race:american_indian_alaska_native": (
            r"american indian",
            r"alaska native",
            r"american indian or alaska native",
            r"native american",
        ),
        "race:native_hawaiian_pacific_islander": (
            r"native hawaiian",
            r"pacific islander",
            r"native hawaiian or other pacific islander",
        ),
        "race:other": (
            r"other",
            r"some other race",
        ),
    }
)


def regulate_race_ethnicity(label: str) -> str:
    """Canonicalize common U.S. EEO race/ethnicity choices."""
    return _regulate(label, _RACE_RULES)


COMMON_DROPDOWN_REGULATORS: Mapping[str, Regulator] = {
    "yes_no": regulate_yes_no,
    "veteran": regulate_veteran_status,
    "gender": regulate_gender,
    "race_ethnicity": regulate_race_ethnicity,
    "disability": regulate_disability_status,
}


def match_regulated_option(
    options: Sequence[OptionT],
    requested_label: str,
    regulator: Regulator,
) -> OptionT:
    """Prefer a normalized exact match, then require one semantic match."""
    requested_normalized = normalize_dropdown_label(requested_label)
    exact_matches = [
        option
        for option in options
        if normalize_dropdown_label(option.label) == requested_normalized
    ]

    if len(exact_matches) == 1:
        return exact_matches[0]

    if len(exact_matches) > 1:
        raise ValueError(
            f"Multiple options exactly match {requested_label!r}: "
            f"{[option.label for option in exact_matches]!r}"
        )

    requested_key = regulator(requested_label)
    matches = [option for option in options if regulator(option.label) == requested_key]

    if not matches:
        raise LookupError(
            f"No option semantically matches {requested_label!r}; "
            f"available labels: {[option.label for option in options]!r}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Multiple options semantically match {requested_label!r}: "
            f"{[option.label for option in matches]!r}"
        )

    return matches[0]


def _match_standard_option(
    options: Sequence[OptionT],
    requested_option: str,
    namespace: str,
    regulator: Regulator,
) -> OptionT:
    """Match a standard option value against labels used by a dropdown."""
    requested_key = f"{namespace}:{requested_option}"
    matches = [option for option in options if regulator(option.label) == requested_key]

    if not matches:
        raise LookupError(
            f"No option semantically matches {requested_option!r}; "
            f"available labels: {[option.label for option in options]!r}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Multiple options semantically match {requested_option!r}: "
            f"{[option.label for option in matches]!r}"
        )

    return matches[0]


def match_yes_no_option(
    options: Sequence[OptionT],
    requested_option: YesNoOption,
) -> OptionT:
    """Match a standard yes/no option against the available labels."""
    return _match_standard_option(options, requested_option, "answer", regulate_yes_no)


def match_veteran_option(
    options: Sequence[OptionT],
    requested_option: VeteranOption,
) -> OptionT:
    """Match a standard veteran-status option against the available labels."""
    return _match_standard_option(options, requested_option, "veteran", regulate_veteran_status)


def match_disability_option(
    options: Sequence[OptionT],
    requested_option: DisabilityOption,
) -> OptionT:
    """Match a standard disability-status option against the available labels."""
    return _match_standard_option(
        options,
        requested_option,
        "disability",
        regulate_disability_status,
    )


def match_veteran_status_option(
    options: Sequence[OptionT],
    requested_option: VeteranStatusOption,
) -> OptionT:
    """Match a standard veteran-status option against the available labels."""
    return match_veteran_option(options, requested_option)


def match_disability_status_option(
    options: Sequence[OptionT],
    requested_option: DisabilityStatusOption,
) -> OptionT:
    """Match a standard disability-status option against the available labels."""
    return match_disability_option(options, requested_option)


def match_gender_option(
    options: Sequence[OptionT],
    requested_option: GenderOption,
) -> OptionT:
    """Match a standard gender option against the available labels."""
    return _match_standard_option(options, requested_option, "gender", regulate_gender)


def match_race_ethnicity_option(
    options: Sequence[OptionT],
    requested_option: RaceEthnicityOption,
) -> OptionT:
    """Match a standard race/ethnicity option against the available labels."""
    return _match_standard_option(
        options,
        requested_option,
        "race",
        regulate_race_ethnicity,
    )
