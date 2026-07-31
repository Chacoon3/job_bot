from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.candidate_profile_models import CandidateProfileRecord
from job_bot.schemas import CandidateProfile


def test_candidate_profile_table_stores_explicit_versioned_fields() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(CandidateProfileRecord.__table__).compile(dialect=dialect))
    index_ddl = [
        str(CreateIndex(index).compile(dialect=dialect))
        for index in CandidateProfileRecord.__table__.indexes
    ]
    column_names = set(CandidateProfileRecord.__table__.columns.keys())

    assert set(CandidateProfile.model_fields) <= column_names
    assert "candidate_id UUID NOT NULL" in ddl
    assert "version INTEGER NOT NULL" in ddl
    assert "first_name VARCHAR(255) NOT NULL" in ddl
    assert "email VARCHAR(320) NOT NULL" in ddl
    assert "authorized_to_work VARCHAR(16) NOT NULL" in ddl
    assert "race VARCHAR(64) NOT NULL" in ddl
    assert "education JSONB NOT NULL" in ddl
    assert "resume_text TEXT NOT NULL" in ddl
    assert "summary TEXT NOT NULL" in ddl
    assert "\n\tprofile " not in ddl
    assert "CONSTRAINT ck_candidate_profiles_version_positive CHECK (version > 0)" in ddl
    assert "CONSTRAINT uq_candidate_profiles_candidate_version UNIQUE" in ddl
    assert any("(candidate_id, version)" in statement for statement in index_ddl)
    assert (
        "CREATE INDEX idx_candidate_profiles_email_latest_active "
        "ON candidate_profiles (email, created_at DESC, id DESC) "
        "WHERE deleted_at IS NULL"
    ) in index_ddl
