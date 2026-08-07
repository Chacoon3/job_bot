from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from importlib import import_module
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session
from job_bot.greenhouse.jobs import GreenhouseBoardSyncPolicy
from job_bot.greenhouse.models import DiscoveryConfig, DiscoveryReport
from job_bot.greenhouse.repository import list_boards, upsert_boards
from job_bot.llm import OpenAILLMProvider
from job_bot.schemas import GreenhouseBoardSchema

router = APIRouter(prefix="/api", tags=["job_bot"])


def GreenhouseGlobalDiscoverer(*args, **kwargs):  # pylint: disable=invalid-name
    discoverer = import_module("job_bot.greenhouse.service").GreenhouseGlobalDiscoverer
    return discoverer(*args, **kwargs)


def GreenhouseCompanyDiscoverer(*args, **kwargs):  # pylint: disable=invalid-name
    discoverer = import_module("job_bot.greenhouse.service").GreenhouseCompanyDiscoverer
    return discoverer(*args, **kwargs)


def GreenhouseJobSyncService(*args, **kwargs):  # pylint: disable=invalid-name
    service = import_module("job_bot.greenhouse.jobs").GreenhouseJobSyncService
    return service(*args, **kwargs)


class BoardSortBy(StrEnum):
    VERIFIED_AT = "verified_at"
    ACTIVE_JOB_COUNT = "active_job_count"
    COMPANY_NAME = "company_name"
    TOKEN = "token"


class GreenhouseBoardListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    boards: list[GreenhouseBoardSchema]


class GreenhouseJobSyncResponse(BaseModel):
    boards_queried: int
    boards_failed: int
    jobs_found: int
    jobs_stored: int


@router.get("/boards")
async def get_boards(
    session: Annotated[Session, Depends(get_session)],
    token: str | None = Query(default=None, min_length=1, max_length=255),
    company_name: str | None = Query(default=None, min_length=1, max_length=512),
    crawl_index: str | None = Query(default=None, min_length=1, max_length=64),
    has_open_jobs: bool | None = None,
    min_active_job_count: int | None = Query(default=None, ge=0),
    max_active_job_count: int | None = Query(default=None, ge=0),
    verified_after: datetime | None = None,
    verified_before: datetime | None = None,
    sort_by: BoardSortBy = BoardSortBy.VERIFIED_AT,
    sort_desc: bool = True,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> GreenhouseBoardListResponse:
    boards, total = list_boards(
        session,
        token=token,
        company_name=company_name,
        crawl_index=crawl_index,
        has_open_jobs=has_open_jobs,
        min_active_job_count=min_active_job_count,
        max_active_job_count=max_active_job_count,
        verified_after=verified_after,
        verified_before=verified_before,
        sort_by=sort_by.value,
        sort_desc=sort_desc,
        limit=limit,
        offset=offset,
    )
    return GreenhouseBoardListResponse(
        total=total,
        limit=limit,
        offset=offset,
        boards=[GreenhouseBoardSchema.from_orm_model(board) for board in boards],
    )


@router.post("/boards/discover")
async def discover_boards(
    config: DiscoveryConfig, session: Annotated[Session, Depends(get_session)]
) -> DiscoveryReport:
    if config.approach == "global":
        discoverer = GreenhouseGlobalDiscoverer(config)
    else:
        discoverer = GreenhouseCompanyDiscoverer(
            config.company_names or [],
            OpenAILLMProvider(),
            config,
        )

    report = await discoverer.discover()
    upsert_boards(session, report.boards)
    session.commit()
    return report


@router.post("/greenhouse/jobs/sync")
def sync_greenhouse_jobs(
    session: Annotated[Session, Depends(get_session)],
    policy: GreenhouseBoardSyncPolicy = GreenhouseBoardSyncPolicy.RECENTLY_UPDATED,
    board_limit: int | None = Query(default=None, ge=1),
    include_keywords: Annotated[list[str] | None, Query()] = None,
    exclude_keywords: Annotated[list[str] | None, Query()] = None,
) -> GreenhouseJobSyncResponse:
    result = GreenhouseJobSyncService(session).sync(
        policy=policy,
        board_limit=board_limit,
        include_keywords=include_keywords or (),
        exclude_keywords=exclude_keywords or (),
    )
    session.commit()
    return GreenhouseJobSyncResponse.model_validate(result, from_attributes=True)
