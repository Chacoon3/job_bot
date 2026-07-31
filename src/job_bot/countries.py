"""Canonical country-name normalization shared by forms and user models."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

_COUNTRY_ALIASES: Mapping[str, str] = {
    "ae": "United Arab Emirates",
    "are": "United Arab Emirates",
    "au": "Australia",
    "aus": "Australia",
    "ca": "Canada",
    "can": "Canada",
    "cn": "China",
    "chn": "China",
    "de": "Germany",
    "deu": "Germany",
    "fr": "France",
    "fra": "France",
    "gb": "United Kingdom",
    "gbr": "United Kingdom",
    "greatbritain": "United Kingdom",
    "in": "India",
    "ind": "India",
    "jp": "Japan",
    "jpn": "Japan",
    "kr": "South Korea",
    "kor": "South Korea",
    "mx": "Mexico",
    "mex": "Mexico",
    "nz": "New Zealand",
    "nzl": "New Zealand",
    "prc": "China",
    "republicofkorea": "South Korea",
    "roc": "Taiwan",
    "ru": "Russia",
    "rus": "Russia",
    "russianfederation": "Russia",
    "sg": "Singapore",
    "sgp": "Singapore",
    "southkorea": "South Korea",
    "uae": "United Arab Emirates",
    "uk": "United Kingdom",
    "unitedarabemirates": "United Arab Emirates",
    "unitedkingdom": "United Kingdom",
    "us": "United States",
    "usa": "United States",
    "unitedstates": "United States",
    "unitedstatesofamerica": "United States",
}

_PHONE_COUNTRY_CODE_DEFAULTS: Mapping[str, str] = {
    "1": "United States",
    "7": "Russia",
    "33": "France",
    "44": "United Kingdom",
    "49": "Germany",
    "52": "Mexico",
    "61": "Australia",
    "64": "New Zealand",
    "65": "Singapore",
    "81": "Japan",
    "82": "South Korea",
    "86": "China",
    "91": "India",
    "971": "United Arab Emirates",
}


def _normalize_country_label(label: str) -> str:
    normalized = unicodedata.normalize("NFKC", label).casefold()
    normalized = normalized.replace("&", " and ").replace("’", "'")
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _country_name_title(normalized_name: str) -> str:
    minor_words = {"and", "of", "the"}
    return " ".join(
        word if index > 0 and word in minor_words else word.capitalize()
        for index, word in enumerate(normalized_name.split())
    )


def regulate_country(label: str) -> str:
    """Return a full, consistently cased country name."""
    normalized_country = _normalize_country_label(label)
    if not normalized_country:
        return f"raw:{normalized_country}"

    compact_name = normalized_country.replace(" ", "")
    if canonical_name := _COUNTRY_ALIASES.get(compact_name):
        return canonical_name

    return _country_name_title(normalized_country)


def regulate_phone_country_code(label: str) -> str:
    """Return the canonical country name represented by a phone option."""
    display_label = unicodedata.normalize("NFKC", label).casefold()
    calling_code_match = re.search(r"\+\s*(\d+)", display_label)
    country_label = re.sub(r"\(?\+\s*\d+(?:[\s-]\d+)*\)?", " ", display_label)
    normalized_country = _normalize_country_label(country_label)

    if normalized_country:
        return regulate_country(normalized_country)

    if calling_code_match:
        calling_code = calling_code_match.group(1)
        if canonical_name := _PHONE_COUNTRY_CODE_DEFAULTS.get(calling_code):
            return canonical_name

    return f"raw:{_normalize_country_label(label)}"
