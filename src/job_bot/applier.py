from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from langchain_core.tools import BaseTool, tool
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

WaitUntil = Literal["load", "domcontentloaded", "networkidle", "commit"]
SelectBy = Literal["value", "label", "index"]


@dataclass
class BrowserSession:
    headless: bool = True
    default_timeout_ms: int = 10000
    viewport_width: int = 1440
    viewport_height: int = 2000
    _playwright: Playwright | None = field(default=None, init=False)
    _browser: Browser | None = field(default=None, init=False)
    _context: BrowserContext | None = field(default=None, init=False)
    _page: Page | None = field(default=None, init=False)

    def start(self, headless: bool | None = None) -> str:
        if self._page is not None:
            return "Browser session is already started."

        if headless is not None:
            self.headless = headless

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height}
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)
        return "Browser session started."

    def stop(self) -> str:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None
        return "Browser session stopped."

    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser session is not started. Call browser_start first.")
        return self._page


def _select_option(page: Page, selector: str, option: str, select_by: SelectBy) -> None:
    if select_by == "label":
        page.locator(selector).first.select_option(label=option)
        return
    if select_by == "index":
        page.locator(selector).first.select_option(index=int(option))
        return
    page.locator(selector).first.select_option(value=option)


def build_browser_tools(session: BrowserSession) -> list[BaseTool]:
    @tool("browser_start")
    def browser_start(headless: bool = True) -> str:
        """Start a Playwright browser session. Must be called before interaction tools."""
        return session.start(headless=headless)

    @tool("browser_stop")
    def browser_stop() -> str:
        """Stop and clean up the browser session."""
        return session.stop()

    @tool("browser_open_url")
    def browser_open_url(url: str, wait_until: WaitUntil = "domcontentloaded") -> str:
        """Navigate to a URL."""
        page = session.page()
        page.goto(url, wait_until=wait_until)
        return f"Opened {url}"

    @tool("browser_click")
    def browser_click(selector: str) -> str:
        """Click an element by CSS/XPath/text selector."""
        page = session.page()
        page.locator(selector).first.click()
        return f"Clicked {selector}"

    @tool("browser_fill_text")
    def browser_fill_text(selector: str, text: str) -> str:
        """Fill a text field by selector."""
        page = session.page()
        page.locator(selector).first.fill(text)
        return f"Filled {selector}"

    @tool("browser_select_dropdown")
    def browser_select_dropdown(
        selector: str,
        option: str,
        select_by: SelectBy = "value",
    ) -> str:
        """Select a dropdown option by value, label, or index."""
        page = session.page()
        _select_option(page, selector=selector, option=option, select_by=select_by)
        return f"Selected option '{option}' in {selector} using {select_by}"

    @tool("browser_set_checkbox")
    def browser_set_checkbox(selector: str, checked: bool) -> str:
        """Set a checkbox/radio control to true or false state."""
        page = session.page()
        locator = page.locator(selector).first
        is_checked = locator.is_checked()
        if checked and not is_checked:
            locator.check()
        if not checked and is_checked:
            locator.uncheck()
        return f"Set {selector} to {checked}"

    @tool("browser_click_boolean_icon")
    def browser_click_boolean_icon(
        true_selector: str,
        false_selector: str,
        value: bool,
    ) -> str:
        """Click a true/false icon using separate selectors for each state."""
        page = session.page()
        target_selector = true_selector if value else false_selector
        page.locator(target_selector).first.click()
        return f"Clicked {'true' if value else 'false'} icon using {target_selector}"

    @tool("browser_press_key")
    def browser_press_key(selector: str, key: str) -> str:
        """Focus an element and press a key (for example Enter, Tab, Escape)."""
        page = session.page()
        page.locator(selector).first.press(key)
        return f"Pressed {key} on {selector}"

    @tool("browser_wait_for")
    def browser_wait_for(selector: str, timeout_ms: int = 10000) -> str:
        """Wait until an element appears."""
        page = session.page()
        page.locator(selector).first.wait_for(timeout=timeout_ms)
        return f"Element available: {selector}"

    @tool("browser_read_text")
    def browser_read_text(selector: str) -> str:
        """Read visible text from an element."""
        page = session.page()
        text = page.locator(selector).first.inner_text()
        return text.strip()

    return [
        browser_start,
        browser_stop,
        browser_open_url,
        browser_click,
        browser_fill_text,
        browser_select_dropdown,
        browser_set_checkbox,
        browser_click_boolean_icon,
        browser_press_key,
        browser_wait_for,
        browser_read_text,
    ]
