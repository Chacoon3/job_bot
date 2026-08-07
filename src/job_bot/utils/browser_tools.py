from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from playwright.async_api import (
    Browser,
    BrowserContext,
    Frame,
    Locator,
    Page,
    Playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

WaitUntil = Literal["load", "domcontentloaded", "networkidle", "commit"]
SelectBy = Literal["value", "label", "index"]
FileId = Literal["resume", "cover_letter"]


@dataclass(slots=True)
class BrowserSession:
    """Owns a browser, context, and page created from an existing Playwright runtime."""

    playwright: Playwright
    headless: bool = True
    default_timeout_ms: int = 30 * 1000
    viewport_width: int = 1440
    viewport_height: int = 1200
    _browser: Browser | None = field(default=None, init=False, repr=False)
    _context: BrowserContext | None = field(default=None, init=False, repr=False)
    _page: Page | None = field(default=None, init=False, repr=False)
    state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    @property
    def started(self) -> bool:
        return self._browser is not None and self._context is not None

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

    async def ensure_page(self) -> Page:
        """Return a usable page, creating one when the context has no open pages."""
        if self._page is not None and not self._page.is_closed():
            return self._page

        if self._context is not None:
            for page in reversed(self._context.pages):
                if not page.is_closed():
                    self._page = page
                    self._page.set_default_timeout(self.default_timeout_ms)
                    return self._page

        if self._context is None:
            raise RuntimeError("Browser session is not started")

        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)
        return self._page

    def page(self) -> Page:
        """Return the current usable page without performing I/O."""
        if self._page is not None and not self._page.is_closed():
            return self._page
        if self._context is None:
            raise RuntimeError("Browser session is not started")
        for page in reversed(self._context.pages):
            if not page.is_closed():
                self._page = page
                page.set_default_timeout(self.default_timeout_ms)
                return page
        raise RuntimeError("Every page in the browser session has been closed")

    def pages(self) -> list[Page]:
        if self._context is None:
            raise RuntimeError("Browser session is not started")
        return list(self._context.pages)

    def switch_page(self, index: int) -> Page:
        pages = self.pages()
        if index < 0 or index >= len(pages):
            raise ValueError(
                f"Tab index {index} is out of range; available tabs: 0-{len(pages) - 1}"
            )
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


def build_browser_tools(session: BrowserSession) -> list[BaseTool]:
    """Build async-only tools over an already-started browser session."""

    @tool(
        name_or_callable="prepare_for_interaction",
        description="Wait for an element to be visible and scroll it into view.",
    )
    async def prepare_for_interaction(locator: Locator) -> None:
        await locator.wait_for(state="visible", timeout=5_000)
        await locator.scroll_into_view_if_needed(timeout=5_000)

    async def unique_locator(selector: str, frame_index: int = 0) -> Locator:
        matches = session.frame(frame_index).locator(selector)
        count = await matches.count()
        if count == 0:
            raise ValueError(
                f"No element matched {selector!r}. Call browser_inspect_form_controls and use "
                "an exact selector returned by that tool."
            )
        if count > 1:
            raise ValueError(
                f"Selector {selector!r} matched {count} elements. Call "
                "browser_inspect_form_controls and use a unique selector."
            )
        return matches.first

    def success(action: str, **details: object) -> str:
        return json.dumps(
            {"success": True, "action": action, **details},
            ensure_ascii=False,
            indent=2,
        )

    async def assert_element_kind(
        locator: Locator,
        *,
        allowed_tags: set[str],
        allowed_types: set[str] | None = None,
        forbidden_role: str | None = None,
    ) -> tuple[str, str, str]:
        tag = await locator.evaluate("(element) => element.tagName.toLowerCase()")
        input_type = (await locator.get_attribute("type") or "").lower()
        role = (await locator.get_attribute("role") or "").lower()
        if forbidden_role and role == forbidden_role:
            raise ValueError(
                f"This element has role={role!r}. Use " "browser_select_combobox_option instead."
            )
        if tag not in allowed_tags:
            raise ValueError(f"Expected one of {sorted(allowed_tags)}, observed <{tag}>.")
        if allowed_types is not None and input_type not in allowed_types:
            raise ValueError(f"Input type {input_type!r} is incompatible with this tool.")
        if await locator.is_disabled():
            raise ValueError("The matched element is disabled.")
        return tag, input_type, role

    def frame_error(frame_index: int, error: ValueError) -> str:
        page = session.page()
        available_frames = [
            {
                "index": index,
                "main": frame is page.main_frame,
                "name": frame.name,
                "url": frame.url,
            }
            for index, frame in enumerate(page.frames)
        ]
        return json.dumps(
            {
                "error": str(error),
                "requested_frame_index": frame_index,
                "available_frames": available_frames,
                "next_action": (
                    "The page or frame tree changed. Choose an index from available_frames "
                    "and retry this inspection."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    async def browser_select_combobox_option(
        selector: str,
        option: str,
        frame_index: int = 0,
    ) -> str:
        """Select a real option in a custom ARIA combobox; never use fill() for it."""
        frame = session.frame(frame_index)
        combo = await unique_locator(selector, frame_index)
        await prepare_for_interaction(combo)
        if (await combo.get_attribute("role") or "").lower() != "combobox":
            raise ValueError(f"{selector!r} is not an ARIA combobox.")
        await combo.click()
        controls_id = await combo.get_attribute("aria-controls") or await combo.get_attribute(
            "aria-owns"
        )
        if controls_id:
            listbox = frame.locator(f"#{controls_id}")
            option_locator = listbox.get_by_role("option", name=option, exact=True)
        else:
            option_locator = frame.get_by_role("option", name=option, exact=True)

        option_count = await option_locator.count()
        if option_count != 1:
            raise ValueError(
                f"Expected one option named {option!r} in the active listbox; "
                f"found {option_count}."
            )
        await prepare_for_interaction(option_locator)
        await option_locator.click()
        await combo.press("Tab")
        await frame.page.wait_for_timeout(100)

        observed = await combo.evaluate(
            r"""
            (element) => {
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const root =
                element.closest('[class*="control"]') ||
                element.parentElement?.parentElement ||
                element.parentElement;
              const selected = root?.querySelector(
                '[class*="single-value"], [data-value], [aria-selected="true"]'
              );
              const hidden = root?.querySelector('input[type="hidden"]');
              return clean(
                selected?.textContent ||
                hidden?.value ||
                element.getAttribute('aria-valuetext') ||
                ''
              );
            }
            """
        )
        if observed != option:
            raise RuntimeError(
                f"Selection did not persist after blur: expected {option!r}, "
                f"observed {observed!r}."
            )
        return success(
            "select_combobox_option",
            selector=selector,
            expected=option,
            observed=observed,
            frame_index=frame_index,
        )

    async def browser_open_url(
        url: str,
        wait_until: WaitUntil = "domcontentloaded",
    ) -> str:
        """Navigate to a URL. Call browser_inspect_page after every navigation."""
        page = await session.ensure_page()
        response = await page.goto(url, wait_until=wait_until)
        status = response.status if response is not None else "unknown"
        if response is not None and not response.ok:
            raise RuntimeError(f"Navigation to {url} returned HTTP {status}.")
        return (
            f"Opened {url}; HTTP status: {status}. "
            "The page state may have changed; call browser_inspect_page now."
        )

    async def browser_click(selector: str, frame_index: int = 0) -> str:
        """Click an element, follow a newly opened tab, then report the resulting page state."""
        page = session.page()
        pages_before = set(session.pages())
        url_before = page.url
        locator = await unique_locator(selector, frame_index)
        await prepare_for_interaction(locator)
        await locator.click()
        if not page.is_closed():
            await page.wait_for_timeout(500)

        new_pages = [candidate for candidate in session.pages() if candidate not in pages_before]
        if new_pages:
            page = session.switch_page(len(session.pages()) - 1)
            await page.bring_to_front()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except PlaywrightTimeoutError:
                pass
        else:
            page = session.page()

        result = {
            "clicked": selector,
            "opened_new_tab": bool(new_pages),
            "url_before": url_before,
            "url_after": page.url,
            "tab_count": len(session.pages()),
            "next_action": "Call browser_inspect_page before choosing another interaction.",
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    async def browser_fill_text(
        selector: str,
        text: str,
        frame_index: int = 0,
    ) -> str:
        """Fill one text field using an exact selector from browser_inspect_form_controls."""
        locator = await unique_locator(selector, frame_index)
        await prepare_for_interaction(locator)
        tag, input_type, _ = await assert_element_kind(
            locator,
            allowed_tags={"input", "textarea"},
            forbidden_role="combobox",
        )
        forbidden_types = {
            "button",
            "checkbox",
            "file",
            "hidden",
            "image",
            "radio",
            "reset",
            "submit",
        }
        if tag == "input" and input_type in forbidden_types:
            raise ValueError(f"Input type {input_type!r} cannot be used with browser_fill_text.")
        if await locator.get_attribute("readonly") is not None:
            raise ValueError("The matched text field is read-only.")
        await locator.fill(text)
        observed = await locator.input_value()
        if observed != text:
            raise RuntimeError(
                f"Fill verification failed: expected {text!r}, observed {observed!r}."
            )
        return success(
            "fill_text",
            selector=selector,
            expected=text,
            observed=observed,
            frame_index=frame_index,
        )

    async def browser_select_dropdown(
        selector: str,
        option: str,
        select_by: SelectBy = "value",
        frame_index: int = 0,
    ) -> str:
        """Select an option in a native HTML select element."""
        locator = await unique_locator(selector, frame_index)
        await prepare_for_interaction(locator)
        await assert_element_kind(locator, allowed_tags={"select"})
        if select_by == "label":
            selected = await locator.select_option(label=option)
        elif select_by == "index":
            selected = await locator.select_option(index=int(option))
        else:
            selected = await locator.select_option(value=option)
        observed = await locator.locator("option:checked").inner_text()
        return success(
            "select_native_option",
            selector=selector,
            requested=option,
            selected_values=selected,
            observed_label=observed.strip(),
            frame_index=frame_index,
        )

    async def browser_set_checkbox(
        selector: str,
        checked: bool,
        frame_index: int = 0,
    ) -> str:
        """Set a checkbox to the requested checked state."""
        locator = await unique_locator(selector, frame_index)
        await prepare_for_interaction(locator)
        await assert_element_kind(
            locator,
            allowed_tags={"input"},
            allowed_types={"checkbox"},
        )
        if checked:
            await locator.check()
        else:
            await locator.uncheck()
        observed = await locator.is_checked()
        if observed != checked:
            raise RuntimeError(
                f"Checkbox verification failed: expected {checked}, observed {observed}."
            )
        return success(
            "set_checkbox",
            selector=selector,
            expected=checked,
            observed=observed,
            frame_index=frame_index,
        )

    async def browser_click_boolean_icon(
        true_selector: str,
        false_selector: str,
        value: bool,
        frame_index: int = 0,
    ) -> str:
        """Click one of two selectors representing true and false choices."""
        selector = true_selector if value else false_selector
        locator = await unique_locator(selector, frame_index)
        await prepare_for_interaction(locator)
        await locator.click()
        return f"Clicked {'true' if value else 'false'} option using {selector}"

    async def browser_press_key(
        selector: str,
        key: str,
        frame_index: int = 0,
    ) -> str:
        """Focus the first matching element and press a key."""
        locator = await unique_locator(selector, frame_index)
        await prepare_for_interaction(locator)
        await locator.press(key)
        return f"Pressed {key} on {selector}"

    @tool("browser_wait_for")
    async def browser_wait_for(
        selector: str,
        timeout_ms: int = 10_000,
        frame_index: int = 0,
    ) -> str:
        """Wait for the first matching element to become visible."""
        locator = await unique_locator(selector, frame_index)
        await locator.wait_for(
            state="visible",
            timeout=timeout_ms,
        )
        return f"Element is visible: {selector}"

    @tool("browser_read_text")
    async def browser_read_text(selector: str, frame_index: int = 0) -> str:
        """Read visible text from the first matching element."""
        locator = await unique_locator(selector, frame_index)
        text = await locator.inner_text()
        return text.strip()

    @tool("browser_read_page")
    async def browser_read_page(max_chars: int = 20_000) -> str:
        """Read visible text from the current page, truncated to max_chars."""
        text = await session.page().locator("body").inner_text()
        return text[:max_chars]

    @tool("browser_inspect_page")
    async def browser_inspect_page(
        frame_index: int = 0,
        max_interactive: int = 100,
        max_text_chars: int = 4_000,
    ) -> str:
        """Inspect page state, links, buttons, and form summaries.

        This tool does not expose editable field selectors. When an application form is
        present, call browser_inspect_form_controls before filling any field.
        """
        if not 1 <= max_interactive <= 500:
            raise ValueError("max_interactive must be between 1 and 500")
        if not 1 <= max_text_chars <= 20_000:
            raise ValueError("max_text_chars must be between 1 and 20000")
        try:
            frame = session.frame(frame_index)
        except ValueError as error:
            return frame_error(frame_index, error)
        snapshot = await frame.evaluate(
            r"""
            ({ maxInteractive, maxTextChars }) => {
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const quote = (value) => CSS.escape(String(value));
              const visible = (element) => {
                const style = getComputedStyle(element);
                return Boolean(
                  element.getClientRects().length &&
                  style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  style.visibility !== 'collapse'
                );
              };
              const inViewport = (element) => {
                const rect = element.getBoundingClientRect();
                return rect.bottom > 0 && rect.right > 0 &&
                  rect.top < innerHeight && rect.left < innerWidth;
              };
              const hiddenReason = (element) => {
                const style = getComputedStyle(element);
                if (style.display === 'none') return 'display:none';
                if (style.visibility === 'hidden') return 'visibility:hidden';
                if (style.visibility === 'collapse') return 'visibility:collapse';
                if (!element.getClientRects().length) return 'no layout box';
                return '';
              };
              const selectorFor = (element) => {
                if (element.id) return `#${CSS.escape(element.id)}`;
                const testId = element.getAttribute('data-testid');
                if (testId) return `[data-testid="${quote(testId)}"]`;
                const name = element.getAttribute('name');
                if (name) return `${element.tagName.toLowerCase()}[name="${quote(name)}"]`;
                const aria = element.getAttribute('aria-label');
                if (aria) {
                  return `${element.tagName.toLowerCase()}[aria-label="${quote(aria)}"]`;
                }
                const text = clean(element.innerText || element.value);
                if (text && ['A', 'BUTTON'].includes(element.tagName)) {
                  return `text=${text.slice(0, 120)}`;
                }
                const tag = element.tagName.toLowerCase();
                const parent = element.parentElement;
                const siblings = parent
                  ? [...parent.children].filter((item) => item.tagName === element.tagName)
                  : [];
                return siblings.length > 1
                  ? `${tag}:nth-of-type(${siblings.indexOf(element) + 1})`
                  : tag;
              };
              const interactiveSelectors = [
                'a[href]',
                'button',
                'input[type="button"]',
                'input[type="submit"]',
                '[role="button"]',
              ].join(',');
              const interactive = [...document.querySelectorAll(interactiveSelectors)]
                .sort((left, right) => Number(visible(right)) - Number(visible(left)))
                .slice(0, maxInteractive)
                .map((element, index) => ({
                  index,
                  tag: element.tagName.toLowerCase(),
                  text: clean(
                    element.innerText || element.value || element.getAttribute('aria-label')
                  ).slice(0, 300),
                  href: element.href || '',
                  target: element.getAttribute('target') || '',
                  aria_label: element.getAttribute('aria-label') || '',
                  visible: visible(element),
                  in_viewport: inViewport(element),
                  hidden_reason: hiddenReason(element),
                  selector: selectorFor(element),
                }));
              const forms = [...document.forms].map((form, index) => ({
                index,
                id: form.id || '',
                name: form.getAttribute('name') || '',
                action: form.action || '',
                method: (form.method || 'get').toLowerCase(),
                control_count: form.elements.length,
                submit_text: [...form.querySelectorAll('button, input[type="submit"]')]
                  .map((element) => clean(element.innerText || element.value))
                  .filter(Boolean)
                  .join(' | '),
                context: clean(form.innerText).slice(0, 500),
              }));
              return {
                title: document.title,
                heading: clean(document.querySelector('h1')?.innerText),
                viewport: { width: innerWidth, height: innerHeight },
                visible_text: clean(document.body?.innerText).slice(0, maxTextChars),
                interactive,
                forms,
              };
            }
            """,
            {"maxInteractive": max_interactive, "maxTextChars": max_text_chars},
        )
        result = {
            "tab_url": session.page().url,
            "frame_index": frame_index,
            "frame_name": frame.name,
            "frame_url": frame.url,
            **snapshot,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    @tool("browser_set_viewport")
    async def browser_set_viewport(width: int = 1440, height: int = 1200) -> str:
        """Set a fixed viewport for responsive layouts, then inspect the page again."""
        if not 320 <= width <= 3840:
            raise ValueError("width must be between 320 and 3840")
        if not 200 <= height <= 2160:
            raise ValueError("height must be between 200 and 2160")
        page = session.page()
        await page.set_viewport_size({"width": width, "height": height})
        session.viewport_width = width
        session.viewport_height = height
        return (
            f"Viewport set to {width}x{height}. "
            "Responsive layout may have changed; call browser_inspect_page now."
        )

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
        """Select a tab by index. Call browser_inspect_page immediately afterward."""
        page = session.switch_page(index)
        await page.bring_to_front()
        return f"Selected tab {index}: {page.url}. Call browser_inspect_page now."

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
        """Return exact selectors, labels, and options for form controls.

        Call this before filling an application form. Interaction tools must receive the exact
        selector returned here rather than a selector inferred from a label.
        """
        if not 1 <= max_controls <= 500:
            raise ValueError("max_controls must be between 1 and 500")
        try:
            frame = session.frame(frame_index)
        except ValueError as error:
            return frame_error(frame_index, error)
        controls = await frame.evaluate(
            r"""
            (maxControls) => {
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const quote = (value) => CSS.escape(String(value));
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
                    ? [...current.parentElement.children].filter(
                        (item) => item.tagName === current.tagName
                      )
                    : [];
                  const suffix = siblings.length > 1
                    ? `:nth-of-type(${siblings.indexOf(current) + 1})`
                    : '';
                  parts.unshift(`${tag}${suffix}`);
                  current = current.parentElement;
                }
                return parts.join(' > ');
              };
              const labelFor = (element) => {
                const nativeLabels = element.labels
                  ? [...element.labels].map((label) => clean(label.innerText))
                  : [];
                const labelledBy = clean(element.getAttribute('aria-labelledby'))
                  .split(' ')
                  .filter(Boolean)
                  .map((id) => document.getElementById(id))
                  .filter(Boolean)
                  .map((node) => clean(node.innerText || node.textContent));
                return [...new Set([...nativeLabels, ...labelledBy].filter(Boolean))].join(' | ');
              };
              return [...document.querySelectorAll('input, textarea, select, button')]
                .sort((left, right) => Number(Boolean(right.getClientRects().length)) -
                  Number(Boolean(left.getClientRects().length)))
                .map((element) => {
                  const role = element.getAttribute('role') || '';
                  const tag = element.tagName.toLowerCase();
                  const type = element.getAttribute('type') || '';
                  const controlKind =
                    role === 'combobox' && tag !== 'select' ? 'custom_combobox' :
                    tag === 'select' ? 'native_select' :
                    type === 'checkbox' ? 'checkbox' :
                    type === 'radio' ? 'radio' :
                    type === 'file' ? 'file' :
                    ['input', 'textarea'].includes(tag) ? 'text' :
                    tag === 'button' ? 'button' : 'other';
                  const interactionTool = {
                    custom_combobox: 'browser_select_combobox_option',
                    native_select: 'browser_select_dropdown',
                    checkbox: 'browser_set_checkbox',
                    file: 'browser_upload_file',
                    text: 'browser_fill_text',
                    button: 'browser_click',
                  }[controlKind] || '';
                  return {
                  control_kind: controlKind,
                  interaction_tool: interactionTool,
                  options_dynamic: controlKind === 'custom_combobox',
                  tag,
                  type,
                  id: element.id || '',
                  name: element.getAttribute('name') || '',
                  label: labelFor(element),
                  placeholder: element.getAttribute('placeholder') || '',
                  aria_label: element.getAttribute('aria-label') || '',
                  role,
                  aria_controls:
                    element.getAttribute('aria-controls') ||
                    element.getAttribute('aria-owns') || '',
                  expanded: element.getAttribute('aria-expanded') || '',
                  autocomplete: element.getAttribute('autocomplete') || '',
                  required: Boolean(
                    element.required || element.getAttribute('aria-required') === 'true'
                  ),
                  disabled: Boolean(element.disabled),
                  read_only: Boolean(element.readOnly),
                  visible: Boolean(element.getClientRects().length),
                  selector: selectorFor(element),
                  form: element.form
                    ? {
                        id: element.form.id || '',
                        name: element.form.getAttribute('name') || '',
                        action: element.form.action || '',
                        method: (element.form.method || 'get').toLowerCase(),
                        context: clean(element.form.innerText).slice(0, 500),
                      }
                    : null,
                  options: element.tagName === 'SELECT'
                    ? [...element.options].slice(0, 50).map((option) => ({
                        label: clean(option.textContent),
                        value: option.value,
                      }))
                    : [],
                };
                })
                .slice(0, maxControls)
                .map((control, index) => ({ ...control, index }));
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
        try:
            frame = session.frame(frame_index)
        except ValueError as error:
            return frame_error(frame_index, error)
        locator = await unique_locator(selector, frame_index)
        result = await locator.evaluate(
            r"""
            (element) => {
              const clone = element.cloneNode(true);
              clone.querySelectorAll('script, style, noscript, svg').forEach(
                (node) => node.remove()
              );
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
    async def browser_upload_file(
        selector: str,
        file_id: FileId = "resume",
        frame_index: int = 0,
    ) -> str:
        """Upload one approved user-provided file to exactly one file input.

        Use only file IDs exposed in the application context, such as
        'resume' or 'cover_letter'.
        """
        uploadable_file = session.state.get(file_id)
        if uploadable_file is None:
            raise RuntimeError(
                f"Upload failed: file {file_id!r} is not available in session state."
            )
        element = await unique_locator(selector, frame_index)
        await assert_element_kind(
            element,
            allowed_tags={"input"},
            allowed_types={"file"},
        )

        await element.set_input_files(
            {
                "name": uploadable_file.filename,
                "mimeType": uploadable_file.mime_type,
                "buffer": uploadable_file.content,
            }
        )

        return success(
            "upload_file",
            selector=selector,
            file_id=file_id,
            filename=uploadable_file.filename,
            frame_index=frame_index,
            next_action=(
                "Inspect the page for the attached filename, upload progress, "
                "or validation errors."
            ),
        )

    return [
        browser_open_url,
        browser_click,
        browser_fill_text,
        browser_select_dropdown,
        browser_select_combobox_option,
        browser_set_checkbox,
        browser_click_boolean_icon,
        browser_press_key,
        browser_wait_for,
        browser_read_text,
        browser_read_page,
        browser_inspect_page,
        browser_set_viewport,
        browser_list_tabs,
        browser_switch_tab,
        browser_list_frames,
        browser_inspect_form_controls,
        browser_read_dom,
        browser_upload_file,
    ]
