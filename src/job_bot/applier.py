from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langchain_core.tools import BaseTool, tool
from playwright.async_api import Browser, BrowserContext, Frame, Page, Playwright

WaitUntil = Literal["load", "domcontentloaded", "networkidle", "commit"]
SelectBy = Literal["value", "label", "index"]


@dataclass(slots=True)
class BrowserSession:
    """Owns a browser, context, and page created from an existing Playwright runtime."""

    playwright: Playwright
    headless: bool = True
    default_timeout_ms: int = 180 * 1000
    viewport_width: int = 1440
    viewport_height: int = 2000
    _browser: Browser | None = field(default=None, init=False, repr=False)
    _context: BrowserContext | None = field(default=None, init=False, repr=False)
    _page: Page | None = field(default=None, init=False, repr=False)

    @property
    def started(self) -> bool:
        return self._page is not None

    async def start(self, headless: bool | None = None) -> None:
        if self.started:
            return

        if headless is not None:
            self.headless = headless

        self._browser = await self.playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)

    async def stop(self) -> None:
        context, browser = self._context, self._browser
        self._page = None
        self._context = None
        self._browser = None

        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()

    def page(self) -> Page:
        if self._page is not None and not self._page.is_closed():
            return self._page

        if self._context is not None:
            for page in reversed(self._context.pages):
                if not page.is_closed():
                    self._page = page
                    self._page.set_default_timeout(self.default_timeout_ms)
                    return self._page

        if self._page is None:
            raise RuntimeError("Browser session is not started")
        raise RuntimeError("Every page in the browser session has been closed")

    def pages(self) -> list[Page]:
        if self._context is None:
            raise RuntimeError("Browser session is not started")
        return list(self._context.pages)

    def switch_page(self, index: int) -> Page:
        pages = self.pages()
        if index < 0 or index >= len(pages):
            raise ValueError(f"Tab index {index} is out of range; available tabs: 0-{len(pages) - 1}")
        page = pages[index]
        if page.is_closed():
            raise RuntimeError(f"Tab {index} has already been closed")
        self._page = page
        page.set_default_timeout(self.default_timeout_ms)
        return page

    def frame(self, index: int) -> Frame:
        frames = self.page().frames
        if index < 0 or index >= len(frames):
            raise ValueError(
                f"Frame index {index} is out of range; available frames: 0-{len(frames) - 1}"
            )
        return frames[index]

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.stop()


async def _select_option(
    page: Page,
    selector: str,
    option: str,
    select_by: SelectBy,
) -> None:
    locator = page.locator(selector).first
    if select_by == "label":
        await locator.select_option(label=option)
    elif select_by == "index":
        await locator.select_option(index=int(option))
    else:
        await locator.select_option(value=option)


def build_browser_tools(session: BrowserSession) -> list[BaseTool]:
    """Build async-only tools over an already-started browser session."""

    @tool("browser_open_url")
    async def browser_open_url(
        url: str,
        wait_until: WaitUntil = "domcontentloaded",
    ) -> str:
        """Navigate the current page to a URL."""
        response = await session.page().goto(url, wait_until=wait_until)
        status = response.status if response is not None else "unknown"
        return f"Opened {url}; HTTP status: {status}"

    @tool("browser_click")
    async def browser_click(selector: str) -> str:
        """Click the first element matching a CSS, XPath, or text selector."""
        await session.page().locator(selector).first.click()
        return f"Clicked {selector}"

    @tool("browser_fill_text")
    async def browser_fill_text(selector: str, text: str) -> str:
        """Fill the first text field matching a selector."""
        await session.page().locator(selector).first.fill(text)
        return f"Filled {selector}"

    @tool("browser_select_dropdown")
    async def browser_select_dropdown(
        selector: str,
        option: str,
        select_by: SelectBy = "value",
    ) -> str:
        """Select a dropdown option by value, label, or zero-based index."""
        await _select_option(session.page(), selector, option, select_by)
        return f"Selected '{option}' in {selector} by {select_by}"

    @tool("browser_set_checkbox")
    async def browser_set_checkbox(selector: str, checked: bool) -> str:
        """Set a checkbox to the requested checked state."""
        locator = session.page().locator(selector).first
        if checked:
            await locator.check()
        else:
            await locator.uncheck()
        return f"Set {selector} to {checked}"

    @tool("browser_click_boolean_icon")
    async def browser_click_boolean_icon(
        true_selector: str,
        false_selector: str,
        value: bool,
    ) -> str:
        """Click one of two selectors representing true and false choices."""
        selector = true_selector if value else false_selector
        await session.page().locator(selector).first.click()
        return f"Clicked {'true' if value else 'false'} option using {selector}"

    @tool("browser_press_key")
    async def browser_press_key(selector: str, key: str) -> str:
        """Focus the first matching element and press a key."""
        await session.page().locator(selector).first.press(key)
        return f"Pressed {key} on {selector}"

    @tool("browser_wait_for")
    async def browser_wait_for(selector: str, timeout_ms: int = 10_000) -> str:
        """Wait for the first matching element to become visible."""
        await session.page().locator(selector).first.wait_for(
            state="visible",
            timeout=timeout_ms,
        )
        return f"Element is visible: {selector}"

    @tool("browser_read_text")
    async def browser_read_text(selector: str) -> str:
        """Read visible text from the first matching element."""
        text = await session.page().locator(selector).first.inner_text()
        return text.strip()

    @tool("browser_read_page")
    async def browser_read_page(max_chars: int = 20_000) -> str:
        """Read visible text from the current page, truncated to max_chars."""
        text = await session.page().locator("body").inner_text()
        return text[:max_chars]

    @tool("browser_list_tabs")
    async def browser_list_tabs() -> str:
        """List every browser tab and identify the tab currently selected by the agent."""
        selected = session.page()
        tabs = []
        for index, page in enumerate(session.pages()):
            closed = page.is_closed()
            tabs.append(
                {
                    "index": index,
                    "selected": page is selected,
                    "closed": closed,
                    "url": page.url,
                    "title": "" if closed else await page.title(),
                }
            )
        return json.dumps(tabs, ensure_ascii=False, indent=2)

    @tool("browser_switch_tab")
    async def browser_switch_tab(index: int) -> str:
        """Select a browser tab by the index returned from browser_list_tabs."""
        page = session.switch_page(index)
        await page.bring_to_front()
        return f"Selected tab {index}: {page.url}"

    @tool("browser_list_frames")
    async def browser_list_frames() -> str:
        """List the main document and all iframes in the selected tab."""
        page = session.page()
        frames = [
            {
                "index": index,
                "main": frame is page.main_frame,
                "name": frame.name,
                "url": frame.url,
            }
            for index, frame in enumerate(page.frames)
        ]
        return json.dumps(frames, ensure_ascii=False, indent=2)

    @tool("browser_inspect_form_controls")
    async def browser_inspect_form_controls(
        frame_index: int = 0,
        max_controls: int = 100,
    ) -> str:
        """Inspect form controls in a frame, including labels, names, ARIA data, and selectors."""
        if not 1 <= max_controls <= 500:
            raise ValueError("max_controls must be between 1 and 500")
        frame = session.frame(frame_index)
        controls = await frame.evaluate(
            """
            (maxControls) => {
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const quote = (value) => String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
              const selectorFor = (element) => {
                if (element.id) return `#${CSS.escape(element.id)}`;
                if (element.name) {
                  return `${element.tagName.toLowerCase()}[name="${quote(element.name)}"]`;
                }
                const aria = element.getAttribute('aria-label');
                if (aria) {
                  return `${element.tagName.toLowerCase()}[aria-label="${quote(aria)}"]`;
                }
                const placeholder = element.getAttribute('placeholder');
                if (placeholder) {
                  return `${element.tagName.toLowerCase()}[placeholder="${quote(placeholder)}"]`;
                }
                const parts = [];
                let current = element;
                while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 5) {
                  const tag = current.tagName.toLowerCase();
                  const siblings = current.parentElement
                    ? [...current.parentElement.children].filter((item) => item.tagName === current.tagName)
                    : [];
                  const suffix = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : '';
                  parts.unshift(`${tag}${suffix}`);
                  current = current.parentElement;
                }
                return parts.join(' > ');
              };
              const labelFor = (element) => {
                const nativeLabels = element.labels ? [...element.labels].map((label) => clean(label.innerText)) : [];
                const labelledBy = clean(element.getAttribute('aria-labelledby'))
                  .split(' ')
                  .filter(Boolean)
                  .map((id) => document.getElementById(id))
                  .filter(Boolean)
                  .map((node) => clean(node.innerText || node.textContent));
                return [...new Set([...nativeLabels, ...labelledBy].filter(Boolean))].join(' | ');
              };
              return [...document.querySelectorAll('input, textarea, select, button')]
                .slice(0, maxControls)
                .map((element, index) => ({
                  index,
                  tag: element.tagName.toLowerCase(),
                  type: element.getAttribute('type') || '',
                  id: element.id || '',
                  name: element.getAttribute('name') || '',
                  label: labelFor(element),
                  placeholder: element.getAttribute('placeholder') || '',
                  aria_label: element.getAttribute('aria-label') || '',
                  role: element.getAttribute('role') || '',
                  autocomplete: element.getAttribute('autocomplete') || '',
                  required: Boolean(element.required || element.getAttribute('aria-required') === 'true'),
                  disabled: Boolean(element.disabled),
                  read_only: Boolean(element.readOnly),
                  visible: Boolean(element.getClientRects().length),
                  selector: selectorFor(element),
                  options: element.tagName === 'SELECT'
                    ? [...element.options].slice(0, 50).map((option) => ({
                        label: clean(option.textContent),
                        value: option.value,
                      }))
                    : [],
                }));
            }
            """,
            max_controls,
        )
        result = {
            "frame_index": frame_index,
            "frame_name": frame.name,
            "frame_url": frame.url,
            "controls": controls,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    @tool("browser_read_dom")
    async def browser_read_dom(
        selector: str = "body",
        frame_index: int = 0,
        max_chars: int = 20_000,
    ) -> str:
        """Read sanitized HTML for an element inside a selected frame."""
        if not 1 <= max_chars <= 100_000:
            raise ValueError("max_chars must be between 1 and 100000")
        frame = session.frame(frame_index)
        result = await frame.locator(selector).first.evaluate(
            """
            (element) => {
              const clone = element.cloneNode(true);
              clone.querySelectorAll('script, style, noscript, svg').forEach((node) => node.remove());
              clone.querySelectorAll('input, textarea').forEach((node) => {
                node.removeAttribute('value');
                if (node.tagName === 'TEXTAREA') node.textContent = '';
              });
              return clone.outerHTML;
            }
            """
        )
        return result[:max_chars]

    @tool("browser_upload_file")
    async def browser_upload_file(selector: str, file_path: str) -> str:
        """Upload a local file through the first matching file input."""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Upload file does not exist: {path}")
        await session.page().locator(selector).first.set_input_files(str(path))
        return f"Uploaded {path.name} using {selector}"

    return [
        browser_open_url,
        browser_click,
        browser_fill_text,
        browser_select_dropdown,
        browser_set_checkbox,
        browser_click_boolean_icon,
        browser_press_key,
        browser_wait_for,
        browser_read_text,
        browser_read_page,
        browser_list_tabs,
        browser_switch_tab,
        browser_list_frames,
        browser_inspect_form_controls,
        browser_read_dom,
        browser_upload_file,
    ]
