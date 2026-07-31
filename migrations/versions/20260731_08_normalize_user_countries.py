"""Normalize user country columns to canonical full names.

Revision ID: 20260731_08
Revises: 20260730_07
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_08"
down_revision: str | Sequence[str] | None = "20260730_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALIASES = {
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

_CALLING_CODES = {
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


def _canonical_country_expression(column: str, *, phone: bool = False) -> str:
    compact = f"regexp_replace(lower({column}), '[^a-z0-9]+', '', 'g')"
    cases: list[str] = []
    if phone:
        cases.extend(
            f"WHEN {column} ~ '\\+\\s*{code}([^0-9]|$)' THEN '{name}'"
            for code, name in _CALLING_CODES.items()
        )
    cases.extend(f"WHEN {compact} = '{alias}' THEN '{name}'" for alias, name in _ALIASES.items())
    title_name = (
        "regexp_replace(regexp_replace(regexp_replace("
        f"initcap(trim(regexp_replace(lower({column}), '[^[:alnum:]]+', ' ', 'g'))), "
        "' And ', ' and ', 'g'), ' Of ', ' of ', 'g'), ' The ', ' the ', 'g')"
    )
    return "CASE " + " ".join(cases) + f" ELSE {title_name} END"


def upgrade() -> None:
    op.alter_column(
        "users",
        "phone_country",
        existing_type=sa.String(length=16),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.execute(
        f"UPDATE users SET phone_country = "
        f"{_canonical_country_expression('phone_country', phone=True)}"
    )
    op.execute(
        f"UPDATE users SET country = {_canonical_country_expression('country')} "
        "WHERE country IS NOT NULL"
    )


def downgrade() -> None:
    # Canonicalization is intentionally retained. Truncation is required only
    # to restore the old dialing-code-sized column.
    op.alter_column(
        "users",
        "phone_country",
        existing_type=sa.String(length=255),
        type_=sa.String(length=16),
        existing_nullable=False,
        postgresql_using="left(phone_country, 16)",
    )
