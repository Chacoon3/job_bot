from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.user_models import User as ORMUser
from job_bot.schemas import User


def test_users_table_matches_the_pydantic_user_model() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(ORMUser.__table__).compile(dialect=dialect))
    index_ddl = [
        str(CreateIndex(index).compile(dialect=dialect)) for index in ORMUser.__table__.indexes
    ]
    column_names = set(ORMUser.__table__.columns.keys())

    assert set(User.model_fields) <= column_names
    assert ORMUser.__tablename__ == "users"
    assert "id UUID NOT NULL" in ddl
    assert "first_name VARCHAR(255) NOT NULL" in ddl
    assert "email VARCHAR(320) NOT NULL" in ddl
    assert "phone_country VARCHAR(255) NOT NULL" in ddl
    assert "authorized_to_work VARCHAR(16) NOT NULL" in ddl
    assert "education JSONB NOT NULL" in ddl
    assert "resume_text TEXT NOT NULL" in ddl
    assert "resume_filename VARCHAR(512) NOT NULL" in ddl
    assert "created_at TIMESTAMP WITH TIME ZONE" in ddl
    assert "updated_at TIMESTAMP WITH TIME ZONE" in ddl
    assert "deleted_at" not in column_names
    assert "CONSTRAINT uq_users_email UNIQUE (email)" in ddl
    assert "CONSTRAINT ck_users_education_array" in ddl
    assert "CREATE INDEX idx_users_created_at ON users (created_at)" in index_ddl


def test_no_user_profile_table_is_registered() -> None:
    assert "user_profiles" not in ORMUser.metadata.tables
