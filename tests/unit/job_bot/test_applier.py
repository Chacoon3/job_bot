import asyncio
import json
from types import SimpleNamespace

from job_bot.applier import BrowserSession, build_browser_tools


class FakeLocator:
    @property
    def first(self) -> "FakeLocator":
        return self

    async def evaluate(self, expression: str) -> str:
        assert "cloneNode" in expression
        return '<form><input name="email"></form>'


class FakeFrame:
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url

    async def evaluate(self, expression: str, argument: object) -> object:
        if "interactiveSelectors" in expression:
            assert argument == {"maxInteractive": 25, "maxTextChars": 2000}
            return {
                "title": "Software Engineer",
                "heading": "Software Engineer",
                "visible_text": "Software Engineer role description Apply now Job alerts",
                "interactive": [
                    {
                        "text": "Apply now",
                        "href": "https://apply.example.com",
                        "selector": "#apply",
                    }
                ],
                "forms": [
                    {
                        "action": "https://example.com/job-alerts",
                        "context": "Get job alerts by email",
                    }
                ],
            }
        assert "querySelectorAll('input, textarea, select, button')" in expression
        assert argument == 25
        return [
            {
                "tag": "input",
                "type": "email",
                "name": "email",
                "label": "Email address",
                "selector": 'input[name="email"]',
            }
        ]

    def locator(self, selector: str) -> FakeLocator:
        assert selector == "form"
        return FakeLocator()


class FakePage:
    def __init__(self, url: str, title: str, frames: list[FakeFrame]) -> None:
        self.url = url
        self._title = title
        self.frames = frames
        self.main_frame = frames[0]
        self.closed = False
        self.front = False
        self.timeout = 0
        self.click_callback = None

    def is_closed(self) -> bool:
        return self.closed

    def set_default_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    async def title(self) -> str:
        return self._title

    async def bring_to_front(self) -> None:
        self.front = True

    async def set_viewport_size(self, viewport: dict[str, int]) -> None:
        self.viewport = viewport

    def locator(self, selector: str) -> "FakePageLocator":
        return FakePageLocator(self, selector)

    async def wait_for_timeout(self, timeout: int) -> None:
        assert timeout == 500

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        assert state == "domcontentloaded"
        assert timeout == 10_000


class FakePageLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "FakePageLocator":
        return self

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def wait_for(self, state: str) -> None:
        assert state == "visible"

    async def click(self) -> None:
        assert self.selector == "#apply"
        if self.page.click_callback is not None:
            self.page.click_callback()


def _session_with_pages(*pages: FakePage) -> BrowserSession:
    session = BrowserSession(playwright=SimpleNamespace())
    session._context = SimpleNamespace(pages=list(pages))
    session._page = pages[0]
    return session


def _tool(tools: list[object], name: str) -> object:
    return next(item for item in tools if item.name == name)


def test_tab_tools_list_and_switch_active_page() -> None:
    main_frame = FakeFrame("", "https://example.com/job")
    first = FakePage("https://example.com/job", "Job", [main_frame])
    second = FakePage("https://apply.example.com", "Application", [main_frame])
    session = _session_with_pages(first, second)
    tools = build_browser_tools(session)

    listed = json.loads(asyncio.run(_tool(tools, "browser_list_tabs").ainvoke({})))
    switched = asyncio.run(_tool(tools, "browser_switch_tab").ainvoke({"index": 1}))

    assert listed[0]["selected"] is True
    assert listed[1]["url"] == "https://apply.example.com"
    assert switched.startswith("Selected tab 1")
    assert session.page() is second
    assert second.front is True


def test_frame_and_form_inspection_tools_return_structured_context() -> None:
    main_frame = FakeFrame("", "https://example.com/job")
    form_frame = FakeFrame("application", "https://forms.example.com/apply")
    page = FakePage("https://example.com/job", "Job", [main_frame, form_frame])
    tools = build_browser_tools(_session_with_pages(page))

    frames = json.loads(asyncio.run(_tool(tools, "browser_list_frames").ainvoke({})))
    inspection = json.loads(
        asyncio.run(
            _tool(tools, "browser_inspect_form_controls").ainvoke(
                {"frame_index": 1, "max_controls": 25}
            )
        )
    )
    dom = asyncio.run(
        _tool(tools, "browser_read_dom").ainvoke(
            {"selector": "form", "frame_index": 1, "max_chars": 1000}
        )
    )

    assert frames[1] == {
        "index": 1,
        "main": False,
        "name": "application",
        "url": "https://forms.example.com/apply",
    }
    assert inspection["frame_index"] == 1
    assert inspection["controls"][0]["label"] == "Email address"
    assert inspection["controls"][0]["selector"] == 'input[name="email"]'
    assert dom == '<form><input name="email"></form>'


def test_page_inspection_distinguishes_apply_action_from_job_alert_form() -> None:
    frame = FakeFrame("", "https://example.com/job")
    page = FakePage("https://example.com/job", "Software Engineer", [frame])
    tools = build_browser_tools(_session_with_pages(page))

    snapshot = json.loads(
        asyncio.run(
            _tool(tools, "browser_inspect_page").ainvoke(
                {"frame_index": 0, "max_interactive": 25, "max_text_chars": 2000}
            )
        )
    )

    assert snapshot["interactive"][0]["text"] == "Apply now"
    assert snapshot["interactive"][0]["selector"] == "#apply"
    assert snapshot["forms"][0]["context"] == "Get job alerts by email"
    assert "click the relevant Apply control" in snapshot["guidance"]


def test_click_apply_follows_new_application_tab() -> None:
    frame = FakeFrame("", "https://example.com/job")
    job_page = FakePage("https://example.com/job", "Job", [frame])
    application_page = FakePage("https://apply.example.com", "Application", [frame])
    session = _session_with_pages(job_page)
    job_page.click_callback = lambda: session._context.pages.append(application_page)
    tools = build_browser_tools(session)

    result = json.loads(
        asyncio.run(_tool(tools, "browser_click").ainvoke({"selector": "#apply"}))
    )

    assert result["opened_new_tab"] is True
    assert result["url_after"] == "https://apply.example.com"
    assert session.page() is application_page
    assert application_page.front is True


def test_viewport_tool_sets_stable_desktop_layout() -> None:
    frame = FakeFrame("", "https://example.com/job")
    page = FakePage("https://example.com/job", "Job", [frame])
    session = _session_with_pages(page)
    tools = build_browser_tools(session)

    result = asyncio.run(
        _tool(tools, "browser_set_viewport").ainvoke({"width": 1440, "height": 1200})
    )

    assert page.viewport == {"width": 1440, "height": 1200}
    assert session.viewport_width == 1440
    assert session.viewport_height == 1200
    assert "browser_inspect_page" in result


def test_page_recovers_to_latest_open_tab() -> None:
    frame = FakeFrame("", "https://example.com")
    closed = FakePage("https://example.com", "Closed", [frame])
    open_page = FakePage("https://apply.example.com", "Open", [frame])
    closed.closed = True
    session = _session_with_pages(closed, open_page)

    assert session.page() is open_page


def test_stale_frame_index_returns_recoverable_error() -> None:
    frame = FakeFrame("", "https://example.com/job")
    page = FakePage("https://example.com/job", "Job", [frame])
    tools = build_browser_tools(_session_with_pages(page))

    result = json.loads(
        asyncio.run(
            _tool(tools, "browser_inspect_page").ainvoke(
                {"frame_index": 1, "max_interactive": 25, "max_text_chars": 2000}
            )
        )
    )

    assert result["requested_frame_index"] == 1
    assert result["available_frames"] == [
        {
            "index": 0,
            "main": True,
            "name": "",
            "url": "https://example.com/job",
        }
    ]
    assert "retry" in result["next_action"]
