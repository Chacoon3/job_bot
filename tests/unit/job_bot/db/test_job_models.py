from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.job_models import Job, JobPageInspection


def test_job_table_has_nullable_source_without_range_columns() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(Job.__table__).compile(dialect=dialect))
    index_ddl = [
        str(CreateIndex(index).compile(dialect=dialect)) for index in Job.__table__.indexes
    ]

    assert "year_of_experience" not in ddl
    assert "pay_range" not in ddl
    assert "source VARCHAR(64) DEFAULT NULL" in ddl
    assert any("(source)" in statement for statement in index_ddl)


def test_job_table_contains_posting_metadata() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(Job.__table__).compile(dialect=dialect))

    assert Job.__tablename__ == "jobs"
    assert "job_id UUID NOT NULL" in ddl
    assert "url VARCHAR(2048) NOT NULL" in ddl
    assert "job_title VARCHAR(512) NOT NULL" in ddl
    assert "date_posted TIMESTAMP WITH TIME ZONE" in ddl
    assert "CONSTRAINT uq_jobs_url UNIQUE (url)" in ddl


def test_job_page_inspection_uses_job_fk_and_jsonb() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(JobPageInspection.__table__).compile(dialect=dialect))

    assert JobPageInspection.__tablename__ == "job_page_inspections"
    assert "job_id UUID NOT NULL" in ddl
    assert "page_index INTEGER NOT NULL" in ddl
    assert "version VARCHAR(64) NOT NULL" in ddl
    assert "inspection JSONB NOT NULL" in ddl
    assert "FOREIGN KEY(job_id) REFERENCES jobs (job_id) ON DELETE CASCADE" in ddl
    assert "CONSTRAINT ck_job_page_inspections_page_index CHECK (page_index >= 0)" in ddl
    assert (
        "CONSTRAINT uq_job_page_inspections_job_page_version "
        "UNIQUE (job_id, page_index, version)" in ddl
    )
