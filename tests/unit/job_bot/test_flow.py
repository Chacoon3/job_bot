from types import SimpleNamespace

from job_bot.flow import (
    CandidateProfile,
    EducationDegree,
    Interval,
    JobEntry,
    _apply_job,
)


class FakeLocator:
    def __init__(self, name: str, page: "FakePage") -> None:
        self.name = name
        self.page = page

    @property
    def first(self) -> "FakeLocator":
        return self

    def fill(self, value: str) -> None:
        self.page.actions.append(("fill", self.name, value))

    def click(self) -> None:
        self.page.actions.append(("click", self.name))

    def check(self) -> None:
        self.page.actions.append(("check", self.name))

    def select_option(self, label: str | None = None) -> None:
        self.page.actions.append(("select_option", self.name, label))


class FakePage:
    def __init__(self) -> None:
        self.actions: list[tuple[str, ...]] = []

    def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
        self.actions.append(("goto", url, wait_until or "", str(timeout or "")))

    def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        self.actions.append(("wait_for_load_state", state, str(timeout or "")))

    def get_by_label(self, pattern: object, exact: bool = False) -> FakeLocator:
        return FakeLocator(f"label:{_pattern_text(pattern)}", self)

    def get_by_placeholder(self, pattern: object) -> FakeLocator:
        return FakeLocator(f"placeholder:{_pattern_text(pattern)}", self)

    def get_by_role(self, role: str, name: object | None = None) -> FakeLocator:
        return FakeLocator(f"role:{role}:{_pattern_text(name)}", self)


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.context = FakeContext(page)
        self.closed = False

    def new_context(self, viewport: dict[str, int] | None = None) -> FakeContext:
        return self.context

    def close(self) -> None:
        self.closed = True


class FakePlaywrightSession:
    def __init__(self, page: FakePage) -> None:
        self.browser = FakeBrowser(page)
        self.entered = False
        self.exited = False
        self.playwright = SimpleNamespace(chromium=SimpleNamespace(launch=self.launch))

    def __enter__(self) -> SimpleNamespace:
        self.entered = True
        return self.playwright

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.exited = True
        return False

    def launch(self, headless: bool = True) -> FakeBrowser:
        return self.browser


def _pattern_text(pattern: object) -> str:
    text = getattr(pattern, "pattern", None)
    if isinstance(text, str):
        return text
    return str(pattern)


def test_apply_job_fills_fields_and_submits(monkeypatch) -> None:
    page = FakePage()
    session = FakePlaywrightSession(page)
    monkeypatch.setattr("job_bot.flow._sync_playwright_session", lambda: session)

    job = JobEntry(
        job_title="Software Engineer",
        url="https://example.com/jobs/123",
        year_of_experience=Interval(minimum=2, maximum=5),
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build systems",
        pay_range=Interval(minimum=120000, maximum=160000),
    )
    candidate = CandidateProfile(
        name="Alex Doe",
        email="alex@example.com",
        phone="555-0100",
        linkedin_url="https://linkedin.com/in/alexdoe",
        github_url="https://github.com/alexdoe",
        portfolio_url="https://alexdoe.dev",
        education=[
            EducationDegree(
                degree="BS",
                field_of_study="Computer Science",
                institution="State University",
                duration=Interval(minimum=4, maximum=4),
                gpa=3.8,
            )
        ],
        resume_text="Senior Python engineer with cloud and platform experience.",
        require_sponsorship=True,
    )

    _apply_job(job, candidate)

    assert session.entered is True
    assert session.exited is True
    assert session.browser.closed is True
    assert session.browser.context.closed is True
    assert ("goto", job.url, "domcontentloaded", "60000") in page.actions
    assert any(action[0] == "fill" and "name" in action[1] for action in page.actions)
    assert any(action[0] == "fill" and "email" in action[1] for action in page.actions)
    assert any(action[0] == "fill" and "phone" in action[1] for action in page.actions)
    assert any(action[0] == "fill" and "resume" in action[1] for action in page.actions)
    assert any(action[0] == "fill" and "education" in action[1] for action in page.actions)
    assert any(
        action[0] in {"click", "check"} and "sponsorship" in action[1] for action in page.actions
    )
    assert any(action[0] == "click" and "apply" in action[1] for action in page.actions)
    assert any(action[0] == "click" and "submit" in action[1] for action in page.actions)
