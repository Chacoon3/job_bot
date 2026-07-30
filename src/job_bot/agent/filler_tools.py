import json
import random
from typing import Callable

from playwright.async_api import Page, expect

from job_bot.schemas import DropdownOption, DropdownSnapshot
from job_bot.utils.browser_tools import Locator


async def fill_text_field(locator: Locator, value: str) -> None:
    count = await locator.count()
    if count != 1:
        raise LookupError(f"Expected exactly one text field, found {count}")

    await locator.wait_for(state="visible", timeout=5000)

    if not await locator.is_enabled():
        raise ValueError("Text field is disabled")

    if not await locator.is_editable():
        raise ValueError("Text field is not editable")

    await locator.click()
    await locator.press("ControlOrMeta+A")
    await locator.press("Backspace")
    for character in value:
        await locator.press_sequentially(character, delay=random.randint(35, 110))
    await locator.press("Tab")  # Trigger blur/change.

    actual = await locator.input_value()
    if actual != value:
        raise RuntimeError(f"Field did not retain value: expected={value!r}, actual={actual!r}")


def locate_by_accessible_name(
    page: Page,
    accessible_name: str,
    role: str | None = None,
) -> Locator:
    if role:
        return page.get_by_role(
            role,
            name=accessible_name,
            exact=True,
        )

    return page.get_by_label(
        accessible_name,
        exact=True,
    )


class DropdownError(RuntimeError):
    pass


class OptionNotFoundError(DropdownError):
    pass


class AmbiguousOptionError(DropdownError):
    pass


async def extract_dropdown_options(
    page: Page,
    dropdown: Locator,
    *,
    timeout: float = 5_000,
) -> DropdownSnapshot:
    count = await dropdown.count()

    if count != 1:
        raise DropdownError(f"Expected exactly one dropdown, found {count}")

    await dropdown.wait_for(state="visible", timeout=timeout)

    if not await dropdown.is_enabled():
        raise DropdownError("Dropdown is disabled")

    tag = await dropdown.evaluate("element => element.tagName.toLowerCase()")

    if tag == "select":
        return await _extract_native_options(dropdown)

    role = await dropdown.get_attribute("role")

    if role != "combobox":
        raise DropdownError(f"Expected select or combobox, found tag={tag!r}, role={role!r}")

    return await _extract_custom_options(
        page,
        dropdown,
        timeout=timeout,
    )


async def _extract_native_options(
    dropdown: Locator,
) -> DropdownSnapshot:
    raw = await dropdown.locator("option").evaluate_all(
        """
        options => options.map((option, index) => ({
            index,
            label: (option.label || option.textContent || "").trim(),
            value: option.value,
            element_id: option.id || null,
            disabled: option.disabled,
            selected: option.selected
        }))
        """
    )

    return DropdownSnapshot(
        kind="native_select",
        options=[DropdownOption(**item) for item in raw],
        complete=True,
    )


async def _extract_custom_options(
    page: Page,
    dropdown: Locator,
    *,
    timeout: float,
) -> DropdownSnapshot:
    await dropdown.click(timeout=timeout)

    await expect(dropdown).to_have_attribute(
        "aria-expanded",
        "true",
        timeout=timeout,
    )

    # Greenhouse/React Select adds aria-controls only after opening.
    listbox_id = await dropdown.get_attribute("aria-controls")

    if not listbox_id:
        raise DropdownError("Opened combobox does not expose aria-controls")

    # json.dumps creates a safely quoted CSS attribute value.
    listbox = page.locator(f'[role="listbox"][id={json.dumps(listbox_id)}]')

    if await listbox.count() != 1:
        raise DropdownError(f"Could not uniquely resolve listbox {listbox_id!r}")

    await expect(listbox).to_be_visible(timeout=timeout)

    options_locator = listbox.get_by_role("option")

    raw = await options_locator.evaluate_all(
        """
        options => options.map((option, index) => {
            const ariaSelected = option.getAttribute("aria-selected");

            return {
                index,
                label: (
                    option.getAttribute("aria-label")
                    || option.innerText
                    || option.textContent
                    || ""
                ).trim(),
                value:
                    option.getAttribute("data-value")
                    || option.getAttribute("value")
                    || null,
                element_id: option.id || null,
                disabled:
                    option.getAttribute("aria-disabled") === "true"
                    || option.hasAttribute("disabled"),
                selected:
                    ariaSelected === "true"
                        ? true
                        : ariaSelected === "false"
                            ? false
                            : null
            };
        })
        """
    )

    options = [DropdownOption(**item) for item in raw]

    if not options:
        # For example, Location (City) needs a query before options exist.
        return DropdownSnapshot(
            kind="autocomplete",
            options=[],
            complete=False,
            listbox_id=listbox_id,
        )

    return DropdownSnapshot(
        kind="finite_combobox",
        options=options,
        # Verified for this Greenhouse React Select implementation.
        # A generic virtualized dropdown should use None or False.
        complete=True,
        listbox_id=listbox_id,
    )


async def select_dropdown_option(
    page: Page,
    dropdown: Locator,
    option_label: str,
    regulator: Callable[[str], str] | None = None,
    *,
    timeout: float = 5_000,
) -> None:
    snapshot = await extract_dropdown_options(
        page,
        dropdown,
        timeout=timeout,
    )

    if not snapshot.options:
        raise OptionNotFoundError("Dropdown has no options")

    option_map: dict[str, str] = {
        regulator(o.label) if regulator else o.label: o for o in snapshot.options
    }
    matches = [option_map.get(regulator(option_label) if regulator else option_label)]

    if not matches:
        raise OptionNotFoundError(f"No matching option found for label {option_label!r}")

    if len(matches) > 1:
        raise AmbiguousOptionError(
            f"Multiple matching options found for label {option_label!r}: {matches}"
        )

    match = matches[0]

    if match.disabled:
        raise ValueError(f"Matching option is disabled: {match}")

    # Use the element ID if available, otherwise use the index.
    selector = (
        f"#{match.element_id}"
        if match.element_id
        else f'[role="option"]:nth-child({match.index + 1})'
    )

    listbox_locator = page.locator(f'[role="listbox"][id={json.dumps(snapshot.listbox_id)}]')

    await expect(listbox_locator).to_be_visible(timeout=timeout)

    option_locator = listbox_locator.locator(selector)

    await expect(option_locator).to_be_visible(timeout=timeout)
