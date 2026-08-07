import asyncio
from types import SimpleNamespace

from job_bot.applier.flow import apply_job
from job_bot.data.schemas import EducationDegree, JobEntrySchema, User


class FakeAsyncPlaywrightContext:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.playwright = SimpleNamespace()

    async def __aenter__(self) -> SimpleNamespace:
        self.entered = True
        return self.playwright

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.exited = True
        return False


class FakeBrowserSession:
    created: list["FakeBrowserSession"] = []

    def __init__(self, playwright: object, headless: bool) -> None:
        self.playwright = playwright
        self.headless = headless
        self.started = False
        self.stopped = False
        FakeBrowserSession.created.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FakeModelProvider:
    def __init__(self, *, parallel_tool_calls: bool) -> None:
        self.parallel_tool_calls = parallel_tool_calls

    def get_model(self) -> str:
        return "fake-model"


class FakeAgent:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        self.payload = payload
        return {"status": "applied"}


def test_apply_job_fills_fields_and_submits(monkeypatch) -> None:
    playwright_context = FakeAsyncPlaywrightContext()
    fake_agent = FakeAgent()
    captured_create_agent: dict[str, object] = {}

    def fake_create_agent(**kwargs):
        captured_create_agent.update(kwargs)
        return fake_agent

    monkeypatch.setattr("job_bot.applier.flow.async_playwright", lambda: playwright_context)
    monkeypatch.setattr("job_bot.applier.flow.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("job_bot.applier.flow.build_browser_tools", lambda session: ["fake-tool"])
    monkeypatch.setattr("job_bot.applier.flow.OpenAILLMProvider", FakeModelProvider)
    monkeypatch.setattr("job_bot.applier.flow.create_agent", fake_create_agent)

    job = JobEntrySchema(
        job_title="Software Engineer",
        source="greenhouse",
        url="https://example.com/jobs/123",
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build systems",
    )
    candidate = User(
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        phone_country="+1",
        phone="555-0100",
        linkedin_url="https://linkedin.com/in/alexdoe",
        github_url="https://github.com/alexdoe",
        portfolio_url="https://alexdoe.dev",
        education=[
            EducationDegree(
                degree="BS",
                field_of_study="Computer Science",
                institution="State University",
                duration_minimum=4,
                duration_maximum=4,
                gpa=3.8,
            )
        ],
        resume_text="Senior Python engineer with cloud and platform experience.",
        requires_sponsorship="yes",
        summary="Senior backend engineer",
    )

    result = asyncio.run(apply_job(job.url, candidate))

    browser_session = FakeBrowserSession.created[-1]

    assert result == {"status": "applied"}
    assert playwright_context.entered is True
    assert playwright_context.exited is True
    assert browser_session.playwright is playwright_context.playwright
    assert browser_session.headless is False
    assert browser_session.started is True
    assert browser_session.stopped is True
    assert captured_create_agent["model"] == "fake-model"
    assert captured_create_agent["tools"] == ["fake-tool"]
    assert "observe-act-observe" in str(captured_create_agent["system_prompt"])
    assert fake_agent.payload is not None
    message = fake_agent.payload["messages"][0]
    assert "Open and apply to the job at https://example.com/jobs/123" in message.content
    assert "User profile:" in message.content
    assert '"first_name": "Alex"' in message.content
    assert '"last_name": "Doe"' in message.content
