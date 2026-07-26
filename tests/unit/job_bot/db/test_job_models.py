from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.job_models import JobEntry


def test_job_entry_table_uses_postgresql_range_types() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(JobEntry.__table__).compile(dialect=dialect))
    index_ddl = [
        str(CreateIndex(index).compile(dialect=dialect)) for index in JobEntry.__table__.indexes
    ]

    assert "year_of_experience INT4RANGE NOT NULL" in ddl
    assert "pay_range INT8RANGE NOT NULL" in ddl
    assert "source VARCHAR(64) NOT NULL" in ddl
    assert "CONSTRAINT ck_job_entries_experience_finite_nonnegative CHECK" in ddl
    assert "CONSTRAINT ck_job_entries_pay_finite_nonnegative CHECK" in ddl
    assert any("USING gist (year_of_experience)" in statement for statement in index_ddl)
    assert any("USING gist (pay_range)" in statement for statement in index_ddl)
    assert any("(source)" in statement for statement in index_ddl)
