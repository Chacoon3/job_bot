from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.application_models import JobApplicationAttempt
from job_bot.db.job_models import Job  # noqa: F401 - register referenced table
from job_bot.db.user_models import User  # noqa: F401 - register referenced table


def test_application_attempt_table_enforces_idempotency_identity() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(JobApplicationAttempt.__table__).compile(dialect=dialect))
    indexes = [
        str(CreateIndex(index).compile(dialect=dialect))
        for index in JobApplicationAttempt.__table__.indexes
    ]

    assert "user_id UUID NOT NULL" in ddl
    assert "job_key VARCHAR(64) NOT NULL" in ddl
    assert "attempt_number INTEGER NOT NULL" in ddl
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in ddl
    assert "FOREIGN KEY(job_id) REFERENCES jobs (job_id) ON DELETE SET NULL" in ddl
    assert "CONSTRAINT ck_job_application_attempts_status" in ddl
    assert "CONSTRAINT uq_job_application_attempts_user_job_number" in ddl
    assert any(
        "CREATE UNIQUE INDEX uq_job_application_attempts_active" in statement
        and "WHERE status IN ('in_progress', 'succeeded')" in statement
        for statement in indexes
    )
