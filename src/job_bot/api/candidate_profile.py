from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session
from job_bot.candidate_profiles import (
    create_profile_version,
    delete_profile_version,
    get_profile_version,
    profile_from_record,
)
from job_bot.db.candidate_profile_models import CandidateProfileRecord
from job_bot.schemas import (
    CandidateProfile,
    CandidateProfileVersion,
    DisabilityStatusOption,
    GenderOption,
    RaceEthnicityOption,
    VeteranStatusOption,
    YesNoOption,
)

router = APIRouter(prefix="/apiv1/candidate_profile", tags=["job_bot"])

MAX_RESUME_BYTES = 10 * 1024 * 1024
SUPPORTED_RESUME_SUFFIXES = {".pdf", ".doc", ".docx"}


class CandidateProfileSupplement(BaseModel):
    """Answers that generally cannot be safely inferred from a resume."""

    phone_country: str | None = Field(default=None, min_length=1, max_length=16)
    authorized_to_work: YesNoOption
    requires_sponsorship: YesNoOption
    willing_to_relocate: YesNoOption
    visa_status: str | None = Field(default=None, max_length=128)
    gender: GenderOption = "decline"
    is_hispanic_or_latino: YesNoOption = "decline"
    race: RaceEthnicityOption = "decline"
    disability_status: DisabilityStatusOption = "decline"
    veteran_status: VeteranStatusOption = "decline"


def _supplement_from_form(
    authorized_to_work: Annotated[YesNoOption, Form()],
    requires_sponsorship: Annotated[YesNoOption, Form()],
    willing_to_relocate: Annotated[YesNoOption, Form()],
    phone_country: Annotated[
        str | None,
        Form(min_length=1, max_length=16),
    ] = None,
    visa_status: Annotated[str | None, Form(max_length=128)] = None,
    gender: Annotated[GenderOption, Form()] = "decline",
    is_hispanic_or_latino: Annotated[YesNoOption, Form()] = "decline",
    race: Annotated[RaceEthnicityOption, Form()] = "decline",
    disability_status: Annotated[DisabilityStatusOption, Form()] = "decline",
    veteran_status: Annotated[VeteranStatusOption, Form()] = "decline",
) -> CandidateProfileSupplement:
    return CandidateProfileSupplement(
        phone_country=phone_country,
        authorized_to_work=authorized_to_work,
        requires_sponsorship=requires_sponsorship,
        willing_to_relocate=willing_to_relocate,
        visa_status=visa_status,
        gender=gender,
        is_hispanic_or_latino=is_hispanic_or_latino,
        race=race,
        disability_status=disability_status,
        veteran_status=veteran_status,
    )


def _extract_candidate_profile(
    resume_content: bytes,
    filename: str,
) -> CandidateProfile:
    """Extract resume fields with an LLM.

    This boundary is intentionally a placeholder. The eventual implementation
    should parse the document, call the configured LLM with structured output,
    and return a validated CandidateProfile.
    """
    del resume_content, filename
    raise NotImplementedError("LLM resume extraction is not implemented")


def _response(record: CandidateProfileRecord) -> CandidateProfileVersion:
    return CandidateProfileVersion(
        candidate_id=record.candidate_id,
        version=record.version,
        profile=profile_from_record(record),
        resume_filename=record.resume_filename,
        created_at=record.created_at,
        deleted_at=record.deleted_at,
    )


@router.get("/{candidate_id}")
def get_candidate_profile(
    candidate_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    version: int | None = Query(default=None, ge=1),
) -> CandidateProfileVersion:
    record = get_profile_version(session, candidate_id, version)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile version not found",
        )
    return _response(record)


@router.put("/{candidate_id}", status_code=status.HTTP_201_CREATED)
async def upload_candidate_profile(
    candidate_id: UUID,
    supplement: Annotated[CandidateProfileSupplement, Depends(_supplement_from_form)],
    resume: Annotated[UploadFile, File(description="PDF or Word resume, up to 10 MiB")],
    session: Annotated[Session, Depends(get_session)],
) -> CandidateProfileVersion:
    filename = Path(resume.filename or "resume").name
    if Path(filename).suffix.casefold() not in SUPPORTED_RESUME_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Resume must be a PDF or Word document",
        )

    content = await resume.read(MAX_RESUME_BYTES + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume is empty",
        )
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Resume exceeds the 10 MiB limit",
        )

    try:
        extracted = _extract_candidate_profile(content, filename)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc

    profile = CandidateProfile.model_validate(
        {
            **extracted.model_dump(),
            **supplement.model_dump(exclude_none=True),
        }
    )
    record = create_profile_version(
        session,
        candidate_id=candidate_id,
        profile=profile,
        resume_filename=filename,
        resume_sha256=hashlib.sha256(content).hexdigest(),
    )
    session.commit()
    session.refresh(record)
    return _response(record)


@router.delete("/{candidate_id}")
def delete_candidate_profile(
    candidate_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    version: int | None = Query(default=None, ge=1),
) -> CandidateProfileVersion:
    record = delete_profile_version(session, candidate_id, version)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile version not found",
        )
    session.commit()
    return _response(record)
