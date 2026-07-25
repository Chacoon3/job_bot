from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.job_models import (
    JobEntryRecord,
    db_range_to_interval_values,
    interval_to_db_range,
)
from job_bot.flow import Interval


def test_job_entry_table_uses_postgresql_range_types() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(JobEntryRecord.__table__).compile(dialect=dialect))
    index_ddl = [
        str(CreateIndex(index).compile(dialect=dialect))
        for index in JobEntryRecord.__table__.indexes
    ]

    assert "year_of_experience INT4RANGE NOT NULL" in ddl
    assert "pay_range INT8RANGE NOT NULL" in ddl
    assert "CONSTRAINT ck_job_entries_experience_finite_nonnegative CHECK" in ddl
    assert "CONSTRAINT ck_job_entries_pay_finite_nonnegative CHECK" in ddl
    assert any("USING gist (year_of_experience)" in statement for statement in index_ddl)
    assert any("USING gist (pay_range)" in statement for statement in index_ddl)


def test_inclusive_interval_converts_to_database_range() -> None:
    value = interval_to_db_range(Interval(minimum=2, maximum=5))

    assert value == Range(2, 5, bounds="[]")


def test_canonical_database_range_converts_to_inclusive_values() -> None:
    assert db_range_to_interval_values(Range(2, 6, bounds="[)")) == (2, 5)
    assert db_range_to_interval_values(Range(2, 5, bounds="[]")) == (2, 5)
