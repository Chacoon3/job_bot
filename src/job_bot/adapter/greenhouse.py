from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import random
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from enum import StrEnum
from pathlib import Path
from time import time
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    import httpx
except ImportError:  # Lets pure parsing/validation tests run without network extras.
    httpx = None  # type: ignore[assignment]


GREENHOUSE_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
    }
)
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
SUPPORTED_ATTACHMENT_SUFFIXES = frozenset({".pdf", ".doc", ".docx", ".txt", ".rtf"})
SAFE_FIELD_NAME = re.compile(r"^[A-Za-z0-9_\-\[\]]{1,200}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


class AdapterError(RuntimeError):
    """Base class for Greenhouse adapter failures."""


class UnsupportedJobUrl(AdapterError):
    pass


class JobUnavailable(AdapterError):
    pass


class TransientGreenhouseError(AdapterError):
    pass


class SchemaError(AdapterError):
    pass


class ApplicationValidationError(AdapterError):
    def __init__(self, issues: Sequence["ValidationIssue"]) -> None:
        self.issues = list(issues)
        super().__init__("; ".join(f"{issue.field}: {issue.message}" for issue in issues))


class FormDriftError(AdapterError):
    pass


class HumanActionRequired(AdapterError):
    pass


class SubmissionAlreadyReserved(AdapterError):
    pass


class FieldKind(StrEnum):
    TEXT = "input_text"
    HIDDEN = "input_hidden"
    TEXTAREA = "textarea"
    FILE = "input_file"
    SINGLE_SELECT = "multi_value_single_select"
    MULTI_SELECT = "multi_value_multi_select"
    BOOLEAN = "boolean"
    UNKNOWN = "unknown"


class QuestionSection(StrEnum):
    BASIC = "questions"
    LOCATION = "location_questions"
    COMPLIANCE = "compliance"
    DATA_COMPLIANCE = "data_compliance"


class SubmissionStatus(StrEnum):
    FILLED = "filled"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"
    HUMAN_ACTION_REQUIRED = "human_action_required"


class LedgerStatus(StrEnum):
    RESERVED = "reserved"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class GreenhouseJobRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    board_token: str
    job_id: int
    source_token: str | None = None
    original_url: str

    @field_validator("board_token")
    @classmethod
    def validate_board_token(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("invalid Greenhouse board token")
        return value

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("job_id must be positive")
        return value


class Choice(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    value: str | int | float | bool
    label: str


class ApplicationField(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    name: str
    kind: FieldKind = Field(alias="type")
    choices: tuple[Choice, ...] = Field(default_factory=tuple, alias="values")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not SAFE_FIELD_NAME.fullmatch(value):
            raise ValueError(f"unsafe or unsupported field name: {value!r}")
        return value


class ApplicationQuestion(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    label: str
    required: bool = False
    fields: tuple[ApplicationField, ...]
    section: QuestionSection = QuestionSection.BASIC


class GreenhouseApplicationSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    questions: tuple[ApplicationQuestion, ...]
    demographic_questions: dict[str, Any] | None = None
    raw_data_compliance: tuple[dict[str, Any], ...] = ()

    def field_index(self) -> dict[str, tuple[ApplicationQuestion, ApplicationField]]:
        index: dict[str, tuple[ApplicationQuestion, ApplicationField]] = {}
        for question in self.questions:
            for field in question.fields:
                if field.name in index:
                    raise SchemaError(f"duplicate Greenhouse field name: {field.name}")
                index[field.name] = (question, field)
        return index


class GreenhouseJob(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    ref: GreenhouseJobRef
    title: str
    company_name: str | None = None
    location: str | None = None
    absolute_url: str
    content_html: str | None = None
    updated_at: str | None = None
    first_published: str | None = None
    application_deadline: str | None = None
    schema_: GreenhouseApplicationSchema = Field(alias="schema")
    raw: dict[str, Any] = Field(repr=False)

    @property
    def schema(self) -> GreenhouseApplicationSchema:
        return self.schema_


class Upload(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    content: bytes = Field(repr=False)
    mime_type: str | None = None

    @field_validator("filename")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if not value or Path(value).name != value:
            raise ValueError("filename must be a non-empty basename")
        return value

    @property
    def resolved_mime_type(self) -> str:
        return (
            self.mime_type or mimetypes.guess_type(self.filename)[0] or "application/octet-stream"
        )


AnswerScalar = str | int | float | bool
AnswerValue = AnswerScalar | list[AnswerScalar]


class ApplicationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[str, AnswerValue]
    uploads: dict[str, Upload] = Field(default_factory=dict)
    source_token: str | None = None


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    message: str


class ApplicationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: SubmissionStatus
    job: GreenhouseJobRef
    filled_fields: tuple[str, ...]
    idempotency_key: str | None = None
    message: str
    browser_errors: tuple[str, ...] = ()


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=4, ge=1, le=10)
    base_delay_seconds: float = Field(default=0.4, ge=0)
    max_delay_seconds: float = Field(default=8.0, ge=0)
    jitter_ratio: float = Field(default=0.25, ge=0, le=1)


class SubmissionLedger(Protocol):
    async def reserve(self, key: str) -> bool: ...

    async def finish(self, key: str, status: LedgerStatus) -> None: ...


class InMemorySubmissionLedger:
    """
    Prevents duplicate clicks inside one process.

    Production services should inject a Redis/Postgres implementation that performs
    ``reserve`` atomically and persists RESERVED/SUBMITTED/UNCERTAIN states.
    """

    def __init__(self) -> None:
        self._states: dict[str, LedgerStatus] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, key: str) -> bool:
        async with self._lock:
            if self._states.get(key) in {
                LedgerStatus.RESERVED,
                LedgerStatus.SUBMITTED,
                LedgerStatus.UNCERTAIN,
            }:
                return False
            self._states[key] = LedgerStatus.RESERVED
            return True

    async def finish(self, key: str, status: LedgerStatus) -> None:
        async with self._lock:
            self._states[key] = status


@dataclass(frozen=True, slots=True)
class BrowserPolicy:
    navigation_timeout_ms: int = 30_000
    form_timeout_ms: int = 15_000
    submission_timeout_ms: int = 15_000
    max_attachment_bytes: int = 10 * 1024 * 1024


def parse_greenhouse_job_url(url: str) -> GreenhouseJobRef:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in GREENHOUSE_HOSTS:
        raise UnsupportedJobUrl(f"not a supported Greenhouse-hosted URL: {url}")

    query = parse_qs(parsed.query)
    source_token = _first(query.get("gh_src"))
    parts = [part for part in parsed.path.split("/") if part]

    # Current and legacy hosted forms:
    #   /{board_token}/jobs/{job_id}
    #   /embed/job_app?for={board_token}&token={job_id}
    if len(parts) >= 3 and parts[-2] == "jobs":
        board_token = parts[-3]
        job_text = parts[-1]
    elif parts[:2] == ["embed", "job_app"]:
        board_token = _required_query(query, "for", url)
        job_text = _required_query(query, "token", url)
    else:
        raise UnsupportedJobUrl(f"Greenhouse URL does not identify a job: {url}")

    try:
        job_id = int(job_text)
    except ValueError as exc:
        raise UnsupportedJobUrl(f"invalid Greenhouse job id in URL: {url}") from exc

    return GreenhouseJobRef(
        board_token=board_token,
        job_id=job_id,
        source_token=source_token,
        original_url=url,
    )


def normalize_job(ref: GreenhouseJobRef, payload: Mapping[str, Any]) -> GreenhouseJob:
    try:
        questions: list[ApplicationQuestion] = []
        for section in (
            QuestionSection.BASIC,
            QuestionSection.LOCATION,
            QuestionSection.COMPLIANCE,
        ):
            raw_questions = payload.get(section.value) or []
            if not isinstance(raw_questions, list):
                raise SchemaError(f"{section.value} must be an array")
            questions.extend(_normalize_questions(raw_questions, section))

        raw_data_compliance = payload.get("data_compliance") or []
        if not isinstance(raw_data_compliance, list):
            raise SchemaError("data_compliance must be an array")
        questions.extend(_normalize_data_compliance(raw_data_compliance))

        location_value = payload.get("location")
        location = location_value.get("name") if isinstance(location_value, Mapping) else None
        schema = GreenhouseApplicationSchema(
            questions=tuple(questions),
            demographic_questions=_dict_or_none(payload.get("demographic_questions")),
            raw_data_compliance=tuple(dict(item) for item in raw_data_compliance),
        )
        schema.field_index()  # Detect duplicate names before any browser interaction.

        return GreenhouseJob(
            ref=ref,
            title=str(payload["title"]),
            company_name=_optional_str(payload.get("company_name")),
            location=_optional_str(location),
            absolute_url=str(payload.get("absolute_url") or ref.original_url),
            content_html=_optional_str(payload.get("content")),
            updated_at=_optional_str(payload.get("updated_at")),
            first_published=_optional_str(payload.get("first_published")),
            application_deadline=_optional_str(payload.get("application_deadline")),
            schema=schema,
            raw=dict(payload),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SchemaError):
            raise
        raise SchemaError(f"invalid Greenhouse job payload: {exc}") from exc


def validate_and_canonicalize(
    job: GreenhouseJob,
    draft: ApplicationDraft,
    *,
    max_attachment_bytes: int = 10 * 1024 * 1024,
) -> ApplicationDraft:
    issues: list[ValidationIssue] = []
    index = job.schema.field_index()
    answers: dict[str, AnswerValue] = dict(draft.answers)

    known_transport_fields = {
        "first_name",
        "last_name",
        "email",
        "phone",
        "location",
        "latitude",
        "longitude",
        "country_short_name",
    }
    unknown = (set(answers) | set(draft.uploads)) - set(index) - known_transport_fields
    for name in sorted(unknown):
        issues.append(
            ValidationIssue(field=name, message="field is not present in the current form schema")
        )

    for name in ("first_name", "last_name", "email"):
        if _is_empty(answers.get(name)):
            issues.append(ValidationIssue(field=name, message="is required by Greenhouse"))

    for name in ("first_name", "last_name", "email"):
        value = answers.get(name)
        if isinstance(value, str) and len(value) > 255:
            issues.append(ValidationIssue(field=name, message="must not exceed 255 characters"))
    for name in ("first_name", "last_name", "phone"):
        value = answers.get(name)
        if isinstance(value, str) and URL_PATTERN.search(value):
            issues.append(ValidationIssue(field=name, message="must not contain a URL"))
    email = answers.get("email")
    if isinstance(email, str) and not EMAIL_PATTERN.fullmatch(email.strip()):
        issues.append(ValidationIssue(field="email", message="is not a valid email address"))

    for question in job.schema.questions:
        present = [
            field.name
            for field in question.fields
            if not _is_empty(answers.get(field.name)) or field.name in draft.uploads
        ]
        if question.required and not present:
            issue_name = question.fields[0].name if question.fields else question.label
            issues.append(
                ValidationIssue(
                    field=issue_name,
                    message=f"required question is unanswered: {question.label}",
                )
            )

        for field in question.fields:
            if field.name not in answers:
                continue
            try:
                answers[field.name] = _canonicalize_field_value(field, answers[field.name])
            except ValueError as exc:
                issues.append(ValidationIssue(field=field.name, message=str(exc)))

    location_names = {"location", "latitude", "longitude"}
    if any(not _is_empty(answers.get(name)) for name in location_names):
        for name in sorted(location_names):
            if _is_empty(answers.get(name)):
                issues.append(
                    ValidationIssue(
                        field=name,
                        message="location, latitude, and longitude must be supplied together",
                    )
                )

    for field_name, upload in draft.uploads.items():
        field = index.get(field_name, (None, None))[1]
        if field is not None and field.kind != FieldKind.FILE:
            issues.append(ValidationIssue(field=field_name, message="field does not accept a file"))
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in SUPPORTED_ATTACHMENT_SUFFIXES:
            issues.append(
                ValidationIssue(
                    field=field_name,
                    message=f"unsupported attachment type {suffix or '<none>'}",
                )
            )
        if not upload.content:
            issues.append(ValidationIssue(field=field_name, message="attachment is empty"))
        if len(upload.content) > max_attachment_bytes:
            issues.append(
                ValidationIssue(
                    field=field_name,
                    message=f"attachment exceeds local {max_attachment_bytes}-byte safety limit",
                )
            )

    if issues:
        raise ApplicationValidationError(issues)

    return ApplicationDraft(
        answers=answers,
        uploads=draft.uploads,
        source_token=draft.source_token or job.ref.source_token,
    )


def submission_key(job: GreenhouseJobRef, email: str) -> str:
    normalized = f"greenhouse:{job.board_token.lower()}:{job.job_id}:{email.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class GreenhouseAdapter:
    """
    Async adapter for public Greenhouse discovery and candidate-side browser apply.

    Greenhouse's public GET API supplies the job-specific form schema. Application
    submission uses the hosted browser form because the official POST endpoint
    requires the employer's secret Job Board API key.
    """

    API_BASE_URL = "https://boards-api.greenhouse.io/v1"

    def __init__(
        self,
        *,
        client: Any | None = None,
        retry_policy: RetryPolicy | None = None,
        browser_policy: BrowserPolicy | None = None,
        ledger: SubmissionLedger | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: random.Random | None = None,
    ) -> None:
        if client is None:
            if httpx is None:
                raise RuntimeError("httpx is required: pip install httpx")
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=True,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "job-bot-greenhouse-adapter/1.0",
                },
            )
            self._owns_client = True
        else:
            self._owns_client = False

        self._client = client
        self._retry = retry_policy or RetryPolicy()
        self._browser = browser_policy or BrowserPolicy()
        self._ledger = ledger or InMemorySubmissionLedger()
        self._sleep = sleep
        self._random = random_source or random.Random()

    async def __aenter__(self) -> "GreenhouseAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def supports(url: str) -> bool:
        try:
            parse_greenhouse_job_url(url)
            return True
        except (UnsupportedJobUrl, ValueError):
            return False

    async def get_job(self, url_or_ref: str | GreenhouseJobRef) -> GreenhouseJob:
        ref = parse_greenhouse_job_url(url_or_ref) if isinstance(url_or_ref, str) else url_or_ref
        url = f"{self.API_BASE_URL}/boards/{ref.board_token}/jobs/{ref.job_id}"
        response = await self._get_with_retry(
            url,
            params={"questions": "true", "pay_transparency": "true"},
        )
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SchemaError("Greenhouse returned a non-JSON job response") from exc
        if not isinstance(payload, Mapping):
            raise SchemaError("Greenhouse job response must be a JSON object")
        return normalize_job(ref, payload)

    async def fill_or_submit(
        self,
        page: Any,
        job: GreenhouseJob,
        draft: ApplicationDraft,
        *,
        submit: bool = False,
    ) -> ApplicationResult:
        """
        Fill the hosted form and optionally click submit exactly once.

        ``submit=False`` is the safe default. Once the click occurs, transport or
        UI timeouts return UNCERTAIN and are never retried automatically.
        """

        prepared = validate_and_canonicalize(
            job,
            draft,
            max_attachment_bytes=self._browser.max_attachment_bytes,
        )
        response = await page.goto(
            job.absolute_url or job.ref.original_url,
            wait_until="domcontentloaded",
            timeout=self._browser.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            raise JobUnavailable(f"job page returned HTTP {response.status}")

        scope = await self._find_application_scope(page)
        if await self._has_closed_marker(scope):
            raise JobUnavailable("Greenhouse job is no longer accepting applications")
        if await self._has_challenge(page):
            return ApplicationResult(
                status=SubmissionStatus.HUMAN_ACTION_REQUIRED,
                job=job.ref,
                filled_fields=(),
                message="A CAPTCHA or anti-bot challenge requires manual completion.",
            )

        fields = job.schema.field_index()
        filled: list[str] = []
        errors: list[str] = []

        for name, value in prepared.answers.items():
            question, field = fields.get(
                name,
                (
                    ApplicationQuestion(
                        label=_humanize(name),
                        fields=(
                            ApplicationField(
                                name=name,
                                type=(
                                    FieldKind.HIDDEN
                                    if name in {"latitude", "longitude", "country_short_name"}
                                    else FieldKind.TEXT
                                ),
                            ),
                        ),
                    ),
                    None,
                ),
            )
            if field is None:
                field = question.fields[0]
            try:
                await self._fill_field(scope, question, field, value)
                filled.append(name)
            except FormDriftError as exc:
                errors.append(str(exc))

        for name, upload in prepared.uploads.items():
            question, field = fields[name]
            try:
                await self._upload_field(scope, question, field, upload)
                filled.append(name)
            except FormDriftError as exc:
                errors.append(str(exc))

        if prepared.source_token:
            await self._set_optional_hidden(scope, "mapped_url_token", prepared.source_token)

        if errors:
            raise FormDriftError("; ".join(errors))

        if not submit:
            return ApplicationResult(
                status=SubmissionStatus.FILLED,
                job=job.ref,
                filled_fields=tuple(filled),
                message="Application form filled; submission intentionally not clicked.",
            )

        if await self._has_challenge(page):
            return ApplicationResult(
                status=SubmissionStatus.HUMAN_ACTION_REQUIRED,
                job=job.ref,
                filled_fields=tuple(filled),
                message="A CAPTCHA or anti-bot challenge requires manual completion.",
            )

        submit_button = await self._find_submit_button(scope)
        try:
            await submit_button.scroll_into_view_if_needed()
            # A trial click proves actionability without dispatching a submit event.
            await submit_button.click(
                trial=True,
                timeout=self._browser.form_timeout_ms,
            )
        except Exception as exc:
            return ApplicationResult(
                status=SubmissionStatus.REJECTED,
                job=job.ref,
                filled_fields=tuple(filled),
                message="The submit control was not actionable; no click was dispatched.",
                browser_errors=(type(exc).__name__,),
            )

        key = submission_key(job.ref, str(prepared.answers["email"]))
        if not await self._ledger.reserve(key):
            raise SubmissionAlreadyReserved(
                "This job/email application is already submitted, pending, or uncertain."
            )

        try:
            await submit_button.click(
                no_wait_after=True,
                timeout=self._browser.form_timeout_ms,
            )
        except Exception as exc:
            # Playwright cannot prove that the DOM event was not dispatched. Treat
            # this as uncertain so a caller cannot blindly create a duplicate.
            await self._ledger.finish(key, LedgerStatus.UNCERTAIN)
            return ApplicationResult(
                status=SubmissionStatus.UNCERTAIN,
                job=job.ref,
                filled_fields=tuple(filled),
                idempotency_key=key,
                message="The submit click may have been dispatched; do not auto-retry.",
                browser_errors=(type(exc).__name__,),
            )

        status, message, browser_errors = await self._observe_submission(page, scope)
        ledger_status = {
            SubmissionStatus.SUBMITTED: LedgerStatus.SUBMITTED,
            SubmissionStatus.REJECTED: LedgerStatus.REJECTED,
            SubmissionStatus.UNCERTAIN: LedgerStatus.UNCERTAIN,
        }[status]
        await self._ledger.finish(key, ledger_status)
        return ApplicationResult(
            status=status,
            job=job.ref,
            filled_fields=tuple(filled),
            idempotency_key=key,
            message=message,
            browser_errors=browser_errors,
        )

    async def _get_with_retry(self, url: str, *, params: Mapping[str, str]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 404:
                    raise JobUnavailable("Greenhouse job or board was not found")
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    return response
                last_error = TransientGreenhouseError(
                    f"Greenhouse returned retryable HTTP {response.status_code}"
                )
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            except JobUnavailable:
                raise
            except Exception as exc:
                if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
                    raise AdapterError(
                        f"Greenhouse returned HTTP {exc.response.status_code}"
                    ) from exc
                last_error = exc
                retry_after = None

            if attempt == self._retry.max_attempts:
                break
            await self._sleep(self._backoff(attempt, retry_after))

        raise TransientGreenhouseError(
            f"Greenhouse GET failed after {self._retry.max_attempts} attempts: {last_error}"
        ) from last_error

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(0.0, retry_after), self._retry.max_delay_seconds)
        raw = min(
            self._retry.max_delay_seconds,
            self._retry.base_delay_seconds * (2 ** (attempt - 1)),
        )
        jitter = raw * self._retry.jitter_ratio
        return max(0.0, raw + self._random.uniform(-jitter, jitter))

    async def _find_application_scope(self, page: Any) -> Any:
        clock = asyncio.get_running_loop().time
        deadline = clock() + self._browser.form_timeout_ms / 1000
        apply_clicked = False
        while clock() < deadline:
            candidates = [page, *list(page.frames)]
            for scope in candidates:
                if await self._has_closed_marker(scope):
                    raise JobUnavailable("Greenhouse job is no longer accepting applications")
                application_signal = scope.locator(
                    '[name="first_name"], [name="email"], input[type="email"], '
                    'input[type="file"], [name^="question_"]'
                )
                if await _locator_exists(scope.locator("form")) and await _locator_exists(
                    application_signal
                ):
                    return scope

            if not apply_clicked:
                apply_button = page.get_by_role(
                    "button",
                    name=re.compile(r"^(apply|apply now|apply for this job)$", re.I),
                )
                if await _locator_exists(apply_button):
                    await apply_button.first.click()
                    apply_clicked = True
                else:
                    apply_link = page.get_by_role(
                        "link",
                        name=re.compile(r"^(apply|apply now|apply for this job)$", re.I),
                    )
                    if await _locator_exists(apply_link):
                        await apply_link.first.click()
                        apply_clicked = True
            await self._sleep(0.2)
        raise FormDriftError("could not locate a Greenhouse application form or iframe")

    async def _fill_field(
        self,
        scope: Any,
        question: ApplicationQuestion,
        field: ApplicationField,
        value: AnswerValue,
    ) -> None:
        locator = await self._field_locator(scope, question, field)
        kind = field.kind
        if kind in {FieldKind.TEXT, FieldKind.TEXTAREA}:
            await locator.fill(str(value))
            return
        if kind == FieldKind.HIDDEN:
            await locator.evaluate(
                """(el, value) => {
                    el.value = value;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                str(value),
            )
            return
        if kind == FieldKind.SINGLE_SELECT:
            await self._select_one(scope, question, field, locator, value)
            return
        if kind == FieldKind.MULTI_SELECT:
            values = value if isinstance(value, list) else [value]
            await self._select_many(scope, question, field, locator, values)
            return
        if kind == FieldKind.BOOLEAN:
            checked = _to_bool(value)
            if await locator.get_attribute("type") == "checkbox":
                await locator.set_checked(checked)
            else:
                await locator.fill("true" if checked else "false")
            return
        if kind == FieldKind.FILE:
            raise FormDriftError(f"{field.name}: file answer must be supplied in draft.uploads")
        raise FormDriftError(f"{field.name}: unsupported Greenhouse field type {kind}")

    async def _upload_field(
        self,
        scope: Any,
        question: ApplicationQuestion,
        field: ApplicationField,
        upload: Upload,
    ) -> None:
        locator = await self._field_locator(scope, question, field, include_hidden=True)
        await locator.set_input_files(
            {
                "name": upload.filename,
                "mimeType": upload.resolved_mime_type,
                "buffer": upload.content,
            }
        )

    async def _field_locator(
        self,
        scope: Any,
        question: ApplicationQuestion,
        field: ApplicationField,
        *,
        include_hidden: bool = False,
    ) -> Any:
        selector = f'[name="{_css_string(field.name)}"]'
        locator = scope.locator(selector)
        candidate = await _first_usable(
            locator, include_hidden=include_hidden or field.kind == FieldKind.HIDDEN
        )
        if candidate is not None:
            return candidate

        by_label = scope.get_by_label(re.compile(rf"^{re.escape(question.label)}", re.I))
        candidate = await _first_matching_kind(
            by_label,
            field.kind,
            include_hidden=include_hidden,
        )
        if candidate is not None:
            return candidate
        raise FormDriftError(f"{field.name}: field not found for label {question.label!r}")

    async def _select_one(
        self,
        scope: Any,
        question: ApplicationQuestion,
        field: ApplicationField,
        locator: Any,
        value: AnswerValue,
    ) -> None:
        scalar = value[0] if isinstance(value, list) and value else value
        choice = _choice_for_value(field, scalar)
        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await locator.get_attribute("type") or "").lower()
        if tag == "select":
            await locator.select_option(value=str(choice.value))
        elif input_type == "radio":
            radio = scope.locator(
                f'[name="{_css_string(field.name)}"][value="{_css_string(str(choice.value))}"]'
            )
            candidate = await _first_usable(radio)
            if candidate is None:
                candidate = scope.get_by_label(choice.label, exact=True)
            await candidate.check()
        else:
            await locator.click()
            option = scope.get_by_role("option", name=choice.label, exact=True)
            if not await _locator_exists(option):
                option = scope.get_by_text(choice.label, exact=True)
            await option.first.click()

    async def _select_many(
        self,
        scope: Any,
        question: ApplicationQuestion,
        field: ApplicationField,
        locator: Any,
        values: Sequence[AnswerScalar],
    ) -> None:
        choices = [_choice_for_value(field, value) for value in values]
        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await locator.get_attribute("type") or "").lower()
        if tag == "select":
            await locator.select_option([str(choice.value) for choice in choices])
            return
        if input_type == "checkbox":
            for choice in choices:
                checkbox = scope.locator(
                    f'[name="{_css_string(field.name)}"][value="{_css_string(str(choice.value))}"]'
                )
                candidate = await _first_usable(checkbox)
                if candidate is None:
                    candidate = scope.get_by_label(choice.label, exact=True)
                await candidate.check()
            return

        await locator.click()
        for choice in choices:
            option = scope.get_by_role("option", name=choice.label, exact=True)
            if not await _locator_exists(option):
                option = scope.get_by_text(choice.label, exact=True)
            await option.first.click()

    async def _set_optional_hidden(self, scope: Any, name: str, value: str) -> None:
        locator = scope.locator(f'[name="{_css_string(name)}"]')
        if await _locator_exists(locator):
            await locator.first.evaluate(
                """(el, value) => {
                    el.value = value;
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                value,
            )

    async def _find_submit_button(self, scope: Any) -> Any:
        candidates = scope.locator('button[type="submit"], input[type="submit"]')
        candidate = await _first_usable(candidates)
        if candidate is None:
            candidate = await _first_usable(
                scope.get_by_role(
                    "button",
                    name=re.compile(r"^(submit application|submit|apply)$", re.I),
                )
            )
        if candidate is None:
            raise FormDriftError("submit button not found")
        return candidate

    async def _observe_submission(
        self,
        page: Any,
        original_scope: Any,
    ) -> tuple[SubmissionStatus, str, tuple[str, ...]]:
        clock = asyncio.get_running_loop().time
        deadline = clock() + self._browser.submission_timeout_ms / 1000
        success_pattern = re.compile(
            r"(thank you for applying|application (?:has been )?submitted|thanks for applying)",
            re.I,
        )
        error_selectors = (
            '[role="alert"]',
            ".field-error",
            ".error-message",
            '[data-testid*="error"]',
        )
        while clock() < deadline:
            scopes = [page, *list(page.frames)]
            for scope in scopes:
                if await _locator_exists(scope.get_by_text(success_pattern)):
                    return (
                        SubmissionStatus.SUBMITTED,
                        "Greenhouse displayed an application confirmation.",
                        (),
                    )
                for selector in error_selectors:
                    locator = scope.locator(selector)
                    candidate = await _first_usable(locator)
                    if candidate is not None:
                        text = (await candidate.inner_text()).strip()
                        if text:
                            return (
                                SubmissionStatus.REJECTED,
                                "Greenhouse displayed a validation error.",
                                (text[:500],),
                            )
            await self._sleep(0.25)

        return (
            SubmissionStatus.UNCERTAIN,
            "Submit was clicked once, but no definitive confirmation was observed; do not auto-retry.",
            ("submission confirmation timeout",),
        )

    async def _has_challenge(self, page: Any) -> bool:
        selectors = (
            'iframe[src*="recaptcha"]',
            'iframe[src*="hcaptcha"]',
            'iframe[src*="challenges.cloudflare.com"]',
            ".g-recaptcha",
            ".h-captcha",
            "[data-sitekey][data-callback]",
        )
        for scope in [page, *list(page.frames)]:
            for selector in selectors:
                if await _locator_exists(scope.locator(selector)):
                    return True
        return False

    async def _has_closed_marker(self, scope: Any) -> bool:
        pattern = re.compile(
            r"(job (?:is )?no longer available|no longer accepting applications|position has been filled)",
            re.I,
        )
        return await _locator_exists(scope.get_by_text(pattern))


def _normalize_questions(
    raw_questions: Sequence[Mapping[str, Any]],
    section: QuestionSection,
) -> list[ApplicationQuestion]:
    normalized: list[ApplicationQuestion] = []
    for raw_question in raw_questions:
        if not isinstance(raw_question, Mapping):
            raise SchemaError(f"{section.value} entries must be objects")
        fields: list[ApplicationField] = []
        raw_fields = raw_question.get("fields") or []
        if not isinstance(raw_fields, list) or not raw_fields:
            raise SchemaError(f"question {raw_question.get('label')!r} has no fields")
        for raw_field in raw_fields:
            if not isinstance(raw_field, Mapping):
                raise SchemaError("question field must be an object")
            raw_type = str(raw_field.get("type") or FieldKind.UNKNOWN)
            try:
                kind = FieldKind(raw_type)
            except ValueError:
                kind = FieldKind.UNKNOWN
            raw_values = raw_field.get("values") or []
            choices = tuple(
                Choice(value=value["value"], label=str(value["label"]))
                for value in raw_values
                if isinstance(value, Mapping) and "value" in value and "label" in value
            )
            fields.append(
                ApplicationField(
                    name=str(raw_field["name"]),
                    type=kind,
                    values=choices,
                )
            )
        normalized.append(
            ApplicationQuestion(
                label=str(raw_question.get("label") or fields[0].name),
                required=bool(raw_question.get("required", False)),
                fields=tuple(fields),
                section=section,
            )
        )
    return normalized


def _normalize_data_compliance(
    raw_items: Sequence[Mapping[str, Any]],
) -> list[ApplicationQuestion]:
    questions: list[ApplicationQuestion] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise SchemaError("data_compliance entries must be objects")
        if item.get("type") != "gdpr":
            continue
        separate = "requires_processing_consent" in item or "requires_retention_consent" in item
        if separate:
            definitions = (
                (
                    "data_compliance[gdpr_processing_consent_given]",
                    "GDPR processing consent",
                    bool(item.get("requires_processing_consent")),
                ),
                (
                    "data_compliance[gdpr_retention_consent_given]",
                    "GDPR retention consent",
                    bool(item.get("requires_retention_consent")),
                ),
            )
        else:
            definitions = (
                (
                    "data_compliance[gdpr_consent_given]",
                    "GDPR consent",
                    bool(item.get("requires_consent")),
                ),
            )
        for name, label, required in definitions:
            questions.append(
                ApplicationQuestion(
                    label=label,
                    required=required,
                    fields=(ApplicationField(name=name, type=FieldKind.BOOLEAN),),
                    section=QuestionSection.DATA_COMPLIANCE,
                )
            )
    return questions


def _canonicalize_field_value(
    field: ApplicationField,
    value: AnswerValue,
) -> AnswerValue:
    if field.kind == FieldKind.SINGLE_SELECT:
        if isinstance(value, list):
            if len(value) != 1:
                raise ValueError("single-select field requires exactly one value")
            value = value[0]
        return _choice_for_value(field, value).value
    if field.kind == FieldKind.MULTI_SELECT:
        values = value if isinstance(value, list) else [value]
        return [_choice_for_value(field, item).value for item in values]
    if field.kind == FieldKind.BOOLEAN:
        return _to_bool(value)
    if field.kind == FieldKind.FILE:
        if not _is_empty(value):
            raise ValueError("file field must be supplied through draft.uploads")
    elif isinstance(value, list):
        raise ValueError(f"{field.kind} field does not accept a list")
    return value


def _choice_for_value(field: ApplicationField, value: Any) -> Choice:
    exact = [choice for choice in field.choices if choice.value == value]
    if len(exact) == 1:
        return exact[0]
    text = str(value).strip().casefold()
    matches = [
        choice
        for choice in field.choices
        if str(choice.value).strip().casefold() == text or choice.label.strip().casefold() == text
    ]
    if len(matches) == 1:
        return matches[0]
    allowed = ", ".join(f"{choice.label} ({choice.value})" for choice in field.choices)
    raise ValueError(f"value {value!r} is not an unambiguous option; allowed: {allowed}")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    raise ValueError(f"cannot interpret {value!r} as boolean")


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time())
        except (TypeError, ValueError, OverflowError):
            return None


async def _locator_exists(locator: Any) -> bool:
    try:
        return await locator.count() > 0
    except Exception:
        return False


async def _first_usable(locator: Any, *, include_hidden: bool = False) -> Any | None:
    try:
        count = min(await locator.count(), 20)
        for index in range(count):
            item = locator.nth(index)
            if include_hidden or await item.is_visible():
                return item
    except Exception:
        return None
    return None


async def _first_matching_kind(
    locator: Any,
    kind: FieldKind,
    *,
    include_hidden: bool = False,
) -> Any | None:
    try:
        count = min(await locator.count(), 20)
        for index in range(count):
            item = locator.nth(index)
            if not include_hidden and not await item.is_visible():
                continue
            tag = await item.evaluate("el => el.tagName.toLowerCase()")
            input_type = (await item.get_attribute("type") or "").lower()
            if kind == FieldKind.FILE and input_type != "file":
                continue
            if kind == FieldKind.TEXTAREA and tag != "textarea":
                continue
            if kind == FieldKind.HIDDEN and input_type != "hidden":
                continue
            if kind in {FieldKind.SINGLE_SELECT, FieldKind.MULTI_SELECT} and not (
                tag == "select"
                or input_type in {"radio", "checkbox"}
                or await item.get_attribute("role") == "combobox"
            ):
                continue
            return item
    except Exception:
        return None
    return None


def _css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _first(values: Sequence[str] | None) -> str | None:
    return values[0] if values else None


def _required_query(query: Mapping[str, Sequence[str]], name: str, url: str) -> str:
    value = _first(query.get(name))
    if not value:
        raise UnsupportedJobUrl(f"missing {name!r} in Greenhouse URL: {url}")
    return value


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().title()


__all__ = [
    "AdapterError",
    "ApplicationDraft",
    "ApplicationField",
    "ApplicationQuestion",
    "ApplicationResult",
    "ApplicationValidationError",
    "BrowserPolicy",
    "Choice",
    "FieldKind",
    "FormDriftError",
    "GreenhouseAdapter",
    "GreenhouseApplicationSchema",
    "GreenhouseJob",
    "GreenhouseJobRef",
    "HumanActionRequired",
    "InMemorySubmissionLedger",
    "JobUnavailable",
    "LedgerStatus",
    "QuestionSection",
    "RetryPolicy",
    "SchemaError",
    "SubmissionAlreadyReserved",
    "SubmissionLedger",
    "SubmissionStatus",
    "TransientGreenhouseError",
    "UnsupportedJobUrl",
    "Upload",
    "normalize_job",
    "parse_greenhouse_job_url",
    "submission_key",
    "validate_and_canonicalize",
]
