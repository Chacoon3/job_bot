from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from job_bot.db.company_models import Company
from job_bot.db.job_models import Job


def test_company_table_contains_common_organization_metadata() -> None:
    dialect = postgresql.dialect()
    ddl = str(CreateTable(Company.__table__).compile(dialect=dialect))
    index_ddl = [
        str(CreateIndex(index).compile(dialect=dialect)) for index in Company.__table__.indexes
    ]

    assert Company.__tablename__ == "companies"
    assert "company_id UUID NOT NULL" in ddl
    assert "name VARCHAR(512) NOT NULL" in ddl
    assert "description TEXT" in ddl
    assert "website_url VARCHAR(2048)" in ddl
    assert "careers_url VARCHAR(2048)" in ddl
    assert "industry VARCHAR(255)" in ddl
    assert "employee_count_min INTEGER" in ddl
    assert "is_staffing_agency BOOLEAN DEFAULT false NOT NULL" in ddl
    assert "CONSTRAINT uq_companies_website_url UNIQUE (website_url)" in ddl
    assert any("(name)" in statement for statement in index_ddl)
    assert any("(industry)" in statement for statement in index_ddl)


def test_company_size_and_country_fields_are_guarded() -> None:
    ddl = str(CreateTable(Company.__table__).compile(dialect=postgresql.dialect()))

    assert "CONSTRAINT ck_companies_employee_count_min_nonnegative" in ddl
    assert "CONSTRAINT ck_companies_employee_count_max_nonnegative" in ddl
    assert "CONSTRAINT ck_companies_employee_count_order" in ddl
    assert "CONSTRAINT ck_companies_founded_year" in ddl
    assert "CONSTRAINT ck_companies_country_code" in ddl


def test_jobs_can_reference_company_without_owning_its_lifecycle() -> None:
    ddl = str(CreateTable(Job.__table__).compile(dialect=postgresql.dialect()))

    assert "company_id UUID" in ddl
    assert "FOREIGN KEY(company_id) REFERENCES companies (company_id) ON DELETE SET NULL" in ddl
