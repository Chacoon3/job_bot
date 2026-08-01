import json
import random
from collections.abc import Callable
from typing import Any

from playwright.async_api import Page, expect

from job_bot.openai_client import get_async_openai_client
from job_bot.schemas import DropdownOption, DropdownSnapshot, FormField, PageInspection
from job_bot.utils.browser_tools import Locator
from job_bot.utils.caching import AppRedisCache
from job_bot.utils.hash_helper import schema_string_key


async def fill_text_field(
    locator: Locator,
    value: str,
    canonicalizer: Callable[[str], str] | None = None,
) -> None:
    """Replace and verify the value of one editable text control.

    Args:
        locator: A Playwright locator that must resolve to exactly one visible,
            enabled, editable input or textarea.
        value: The text to enter into the control.
        canonicalizer: Optional function applied to both the requested and
            retained strings before verification. Use it when the page may
            reformat a semantically equivalent value, such as a phone number.
    """
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
    expected_comparison = canonicalizer(value) if canonicalizer else value
    actual_comparison = canonicalizer(actual) if canonicalizer else actual
    if actual_comparison != expected_comparison:
        raise RuntimeError(f"Field did not retain value: expected={value!r}, actual={actual!r}")


def locate_by_accessible_name(
    page: Page,
    accessible_name: str,
    role: str | None = None,
) -> Locator:
    """Build an exact locator for a control's accessible identity.

    Args:
        page: The active Playwright page containing the control.
        accessible_name: The complete accessible name or associated label text.
        role: Optional ARIA role. When provided, role-based lookup is used;
            otherwise the control is located by its associated label.
    """
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
    """Inspect the options currently exposed by one dropdown control.

    Args:
        page: The active Playwright page containing any custom listbox.
        dropdown: A locator resolving to exactly one native ``select`` or ARIA
            ``combobox`` control.
        timeout: Maximum milliseconds for each visibility or state wait.

    Returns:
        A snapshot describing the dropdown kind, available options, and
        associated listbox. An autocomplete may initially contain no options.
    """
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
    """Read options from a native select.

    Args:
        dropdown: A locator for one native ``select`` element already checked
            for visibility and enabled state.
    """
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
    """Open an ARIA combobox and inspect its controlled listbox.

    Args:
        page: The active page used to resolve the controlled listbox by ID.
        dropdown: A locator for one enabled ARIA ``combobox``.
        timeout: Maximum milliseconds for each open and visibility wait.
    """
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

    options = await _read_custom_options(listbox)

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


async def _read_custom_options(listbox: Locator) -> list[DropdownOption]:
    """Convert the current ARIA options within a listbox into model objects.

    Args:
        listbox: A locator for the visible ``role=listbox`` container.
    """
    raw = await listbox.get_by_role("option").evaluate_all(
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

    return [DropdownOption(**item) for item in raw]


async def select_dropdown_option(
    page: Page,
    dropdown: Locator,
    option_label: str,
    regulator: Callable[[str], str] | None = None,
    *,
    query: str | None = None,
    timeout: float = 5_000,
) -> None:
    """Select one semantic option from a native select or custom combobox.

    Args:
        page: The active Playwright page containing the dropdown and listbox.
        dropdown: A locator resolving to exactly one dropdown control.
        option_label: The desired option's canonical or displayed label.
        regulator: Optional canonicalizer applied to the desired label and all
            displayed labels before matching.
        query: Optional text to type when an autocomplete has no initial
            options. Defaults to ``option_label``; callers may provide a more
            specific query such as city, state, and country.
        timeout: Maximum milliseconds for each dropdown state or option wait.
    """
    snapshot = await extract_dropdown_options(
        page,
        dropdown,
        timeout=timeout,
    )

    if snapshot.kind == "autocomplete" and not snapshot.options:
        await dropdown.press("ControlOrMeta+A")
        await dropdown.press("Backspace")
        await dropdown.press_sequentially(
            query or option_label,
            delay=random.randint(35, 110),
        )

        listbox_locator = page.locator(f'[role="listbox"][id={json.dumps(snapshot.listbox_id)}]')
        options_locator = listbox_locator.get_by_role("option")
        await expect(options_locator.nth(0)).to_be_visible(timeout=timeout)
        snapshot.options = await _read_custom_options(listbox_locator)

    if not snapshot.options:
        raise OptionNotFoundError("Dropdown has no options")

    normalize = regulator or (lambda value: value.strip().casefold())
    normalized_target = normalize(option_label)

    matches = [
        option for option in snapshot.options if normalize(option.label) == normalized_target
    ]

    if not matches and snapshot.kind == "autocomplete":
        matches = [
            option
            for option in snapshot.options
            if normalize(option.label).startswith(f"{normalized_target},")
        ]

    if not matches:
        available = [option.label for option in snapshot.options]
        raise OptionNotFoundError(
            f"No matching option found for {option_label!r}; " f"available options: {available}"
        )

    if len(matches) > 1:
        raise AmbiguousOptionError(
            f"Multiple options match {option_label!r}: " f"{[option.label for option in matches]}"
        )

    match = matches[0]

    if match.disabled:
        raise ValueError(f"Matching option is disabled: {match.label!r}")

    listbox_locator = page.locator(f'[role="listbox"][id={json.dumps(snapshot.listbox_id)}]')

    await expect(listbox_locator).to_be_visible(timeout=timeout)

    if match.element_id:
        # Attribute selector avoids having to CSS-escape the ID.
        option_locator = listbox_locator.locator(
            f'[role="option"][id={json.dumps(match.element_id)}]'
        )
    else:
        # nth() counts only elements with role="option", unlike :nth-child().
        option_locator = listbox_locator.get_by_role("option").nth(match.index)

    await expect(option_locator).to_be_visible(timeout=timeout)
    await expect(option_locator).to_be_enabled(timeout=timeout)

    await option_locator.click(timeout=timeout)

    # React Select normally closes the listbox after selection.
    await expect(listbox_locator).to_be_hidden(timeout=timeout)
    await expect(dropdown).to_have_attribute(
        "aria-expanded",
        "false",
        timeout=timeout,
    )


def _infer_field_key(field: dict[str, Any]) -> str:
    """Infer a common application-field key from live DOM metadata.

    Args:
        field: Raw control metadata produced by :func:`inspect_active_page`,
            including names, labels, element type, and group information.
    """
    name = " ".join(
        str(field.get(key) or "")
        for key in ("accessible_name", "input_name", "element_id", "placeholder")
    ).casefold()
    group = str(field.get("group_label") or "").casefold()
    tag = str(field.get("tag") or "").casefold()
    input_type = str(field.get("input_type") or "").casefold()

    # Consent questions often mention the applicant's phone number while asking
    # for a Yes/No communications preference. Classify their purpose before the
    # broader contact-field rules inspect words such as "phone" or "telephone".
    if "consent" in name and any(
        marker in name for marker in ("communication", "sms", "text message", "phone message")
    ):
        return "communications_consent"
    if "country" in name and "phone" in group:
        return "phone_country"
    if input_type == "tel":
        return "phone"
    if "resume" in group or "cv" in group:
        return "attach_resume_button"
    if "cover letter" in group:
        return "attach_cover_letter_button"
    if input_type == "submit" or (tag == "button" and "submit application" in name):
        return "submit_button"

    rules = (
        (("first name", "first_name", "firstname"), "first_name"),
        (("last name", "last_name", "lastname"), "last_name"),
        (("email",), "email"),
        (("phone", "telephone"), "phone"),
        (("location (city)", "city"), "city"),
        (("linkedin",), "linkedin_url"),
        (("github",), "github_url"),
        (("portfolio",), "portfolio_url"),
        (("website",), "website_url"),
        (("sponsorship",), "requires_sponsorship"),
        (("authorized to work", "authorization to work"), "authorized_to_work"),
        (("salary",), "desired_salary"),
        (("veteran",), "veteran_status"),
        (("disability",), "disability_status"),
        (("hispanic", "latino"), "is_hispanic_or_latino"),
        (("gender",), "gender"),
        (("resume", "cv"), "attach_resume_button"),
        (("cover letter",), "attach_cover_letter_button"),
        (("country",), "country"),
    )
    for needles, field_key in rules:
        if any(needle in name for needle in needles):
            return field_key
    return "unknown"


async def inspect_active_page(page: Page) -> PageInspection:
    """Inspect interactive controls in the active Playwright page.

    The browser computes DOM- and accessibility-derived facts in one pass.  No
    network lookup or language-model inference is involved, so the returned
    roles and element identities describe the same page that will be filled.

    Args:
        page: The active Playwright page whose top-level document should be
            inspected for interactive application controls.

    Returns:
        Validated metadata for every discovered interactive control.
    """
    raw_fields = await page.evaluate(
        r"""
        () => {
          const clean = value => (value || '').replace(/\s+/g, ' ').trim();
          const textByIds = value => clean(value).split(' ').filter(Boolean)
            .map(id => document.getElementById(id))
            .filter(Boolean)
            .map(node => clean(node.innerText || node.textContent));
          const labelsFor = element => {
            const native = element.labels
              ? [...element.labels].map(label => clean(label.innerText || label.textContent))
              : [];
            const referenced = textByIds(element.getAttribute('aria-labelledby'));
            return [...new Set([...native, ...referenced].filter(Boolean))];
          };
          const accessibleName = (element, labels) => clean(
            element.getAttribute('aria-label')
            || labels.join(' ')
            || element.getAttribute('title')
            || element.getAttribute('placeholder')
            || (['BUTTON', 'A'].includes(element.tagName)
              ? element.innerText || element.textContent
              : '')
          ).replace(/\s*\*\s*$/, '');
          const groupFor = element => {
            const group = element.closest('fieldset, [role="group"]');
            if (!group) return {key: null, label: null};
            const legend = group.querySelector(':scope > legend');
            const referenced = textByIds(group.getAttribute('aria-labelledby'));
            return {
              key: group.id || group.getAttribute('name') || null,
              label: clean(
                group.getAttribute('aria-label')
                || referenced.join(' ')
                || (legend && (legend.innerText || legend.textContent))
              ) || null,
            };
          };
          const controls = document.querySelectorAll(
            'input, textarea, select, button, a[href], [contenteditable="true"], [role="combobox"]'
          );

          return [...new Set(controls)].map(element => {
            const tag = element.tagName.toLowerCase();
            const role = element.getAttribute('role');
            const type = element.getAttribute('type');
            const labels = labelsFor(element);
            const name = accessibleName(element, labels);
            const group = groupFor(element);
            const isCombobox = role === 'combobox';
            const isNativeSelect = tag === 'select';
            const isContentEditable = element.isContentEditable;
            const interactionStrategy = isNativeSelect ? 'select_native'
              : isCombobox ? 'select_combobox'
              : type === 'radio' ? 'select_radio'
              : type === 'checkbox' ? 'toggle_checkbox'
              : type === 'file' ? 'upload_file'
              : type === 'date' ? 'pick_date'
              : isContentEditable ? 'fill_contenteditable'
              : ['input', 'textarea'].includes(tag) ? 'fill'
              : ['button', 'a'].includes(tag) ? 'click'
              : 'unsupported';
            const controlKind = tag === 'textarea' ? 'textarea'
              : isNativeSelect ? 'select'
              : tag === 'button' || tag === 'a' ? 'button'
              : isContentEditable ? 'contenteditable'
              : tag === 'input' ? 'input'
              : 'unknown';
            const selectedComboboxValue = isCombobox
              ? element.closest('[class*="control"]')?.querySelector('[class*="singleValue"]')
              : null;
            const value = type === 'checkbox' || type === 'radio'
              ? Boolean(element.checked)
              : isCombobox && selectedComboboxValue
                ? clean(selectedComboboxValue.innerText || selectedComboboxValue.textContent)
                : 'value' in element ? element.value || null : null;

            return {
              interaction_strategy: interactionStrategy,
              control_kind: controlKind,
              element_id: element.id || null,
              input_name: element.getAttribute('name'),
              test_id: element.getAttribute('data-testid'),
              tag,
              role,
              input_type: type,
              accessible_name: name || null,
              labels,
              placeholder: element.getAttribute('placeholder'),
              current_value: value,
              options: isNativeSelect ? [...element.options].map(option => ({
                label: clean(option.label || option.textContent),
                value: option.value || null,
                selected: option.selected,
                disabled: option.disabled,
              })) : [],
              required: Boolean(
                element.required || element.getAttribute('aria-required') === 'true'
              ),
              visible: Boolean(element.getClientRects().length),
              enabled: !Boolean(
                element.disabled || element.getAttribute('aria-disabled') === 'true'
              ),
              editable: ['input', 'textarea'].includes(tag) || isContentEditable,
              readonly: Boolean(
                element.readOnly || element.getAttribute('aria-readonly') === 'true'
              ),
              checked: type === 'checkbox' || type === 'radio' ? Boolean(element.checked) : null,
              multiple: Boolean(element.multiple),
              form_id: element.form ? element.form.id || null : null,
              group_key: group.key,
              group_label: group.label,
              component: isCombobox && name.toLowerCase().includes('country')
                && (group.label || '').toLowerCase().includes('phone') ? 'phone_country'
                : name.toLowerCase().includes('phone') ? 'phone_number'
                : 'standalone',
              frame_url: window.location.href,
              frame_name: window.name || null,
            };
          });
        }
        """
    )

    fields: list[FormField] = []
    for raw_field in raw_fields:
        raw_field["field_key"] = _infer_field_key(raw_field)
        fields.append(FormField.model_validate(raw_field))
    return PageInspection(form_fields=fields)


@AppRedisCache.cached(
    key_builder=lambda page, locator, exp_val: schema_string_key("page_inspections", page.url),
    ttl=60 * 60 * 24 * 7,  # 1 week
)
async def llm_infer_correct_dropdown_option(
    page: Page,
    locator: Locator,
    expected_value: str,
) -> str | None:
    """Use an LLM to infer the correct option for a dropdown.

    Args:
        page: The active Playwright page containing the dropdown.
        locator: A locator resolving to exactly one native select or ARIA
            combobox.
        expected_value: The canonical value that should be selected, such as
            "United States" or "California".

    Returns:
        The label of the inferred option, or None if no match could be found.
    """
    model = get_async_openai_client()
    dropdown_options = await extract_dropdown_options(page, locator)
    resp = await model.responses.create(
        model=model.model_name,
        input=[
            {
                "role": "system",
                "content": (
                    "You are an expert in playwright browser automation and web accessibility. "
                    "You are given a dropdown control with a set of options. "
                    "You are also given a canonical value that should be selected. "
                    "Your task is to determine which option best matches the canonical value. "
                    "Return only the label of the best matching option, or 'None' if no match."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Given the canonical value '{expected_value}', "
                    f"and the following dropdown options: {dropdown_options.options}, "
                    "which option should be selected? "
                    "Return only the label of the best matching option, or 'None' if no match."
                ),
            },
        ],
    )

    return resp.text
