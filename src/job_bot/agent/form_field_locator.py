from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from playwright.async_api import Frame, Locator, Page

from job_bot.schemas import FormField

LocatorScope: TypeAlias = Page | Frame | Locator


@dataclass(frozen=True)
class LocatorCandidate:
    strategy: str
    locator: Locator


@dataclass(frozen=True)
class ResolvedField:
    locator: Locator
    strategy: str


class FieldLocatorError(LookupError):
    pass


class FieldNotFoundError(FieldLocatorError):
    pass


class AmbiguousFieldError(FieldLocatorError):
    pass


def css_string(value: str) -> str:
    """Escape a value used inside a quoted CSS attribute selector."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\a ")
        .replace("\r", "\\d ")
        .replace("\f", "\\c ")
    )
    return f'"{escaped}"'


def infer_role(field: FormField) -> str | None:
    if field.role:
        return field.role

    tag = field.tag.lower()
    input_type = (field.input_type or "text").lower()

    if tag == "textarea":
        return "textbox"
    if tag == "select":
        return "listbox" if field.multiple else "combobox"
    if tag == "button":
        return "button"
    if tag != "input":
        return None

    return {
        "text": "textbox",
        "email": "textbox",
        "tel": "textbox",
        "url": "textbox",
        "password": "textbox",
        "search": "searchbox",
        "number": "spinbutton",
        "range": "slider",
        "checkbox": "checkbox",
        "radio": "radio",
        "button": "button",
        "submit": "button",
        "reset": "button",
    }.get(input_type)


def normalize_label(label: str) -> str:
    return re.sub(r"\s*[*:]\s*$", "", label).strip()


def deduplicate_strings(values: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        if not value:
            continue
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def build_attribute_selector(
    field: FormField,
    *,
    include_id: bool,
    minimum_attributes: int = 1,
) -> str | None:
    attributes: list[str] = []

    if include_id and field.element_id:
        attributes.append(f"[id={css_string(field.element_id)}]")
    if field.input_name:
        attributes.append(f"[name={css_string(field.input_name)}]")
    if field.input_type and field.tag.lower() == "input":
        attributes.append(f"[type={css_string(field.input_type)}]")
    if field.options:
        attributes.append(f"[value={css_string(field.options[0].value)}]")
    if field.placeholder:
        attributes.append(f"[placeholder={css_string(field.placeholder)}]")

    if len(attributes) < minimum_attributes:
        return None

    return (field.tag.lower() or "*") + "".join(attributes)


def build_locator_candidates(
    scope: LocatorScope,
    field: FormField,
) -> list[LocatorCandidate]:
    candidates: list[LocatorCandidate] = []

    # 1. Automation-specific attribute.
    if field.test_id:
        candidates.append(LocatorCandidate("test_id", scope.get_by_test_id(field.test_id)))

    # 2. Strong DOM attribute combination. option_value disambiguates radios.
    selector = build_attribute_selector(
        field,
        include_id=False,
        minimum_attributes=1,
    )
    if selector:
        candidates.append(LocatorCandidate("name+tag+type+value", scope.locator(selector)))

    # 3. User-facing accessibility identity.
    role = infer_role(field)
    if role and field.accessible_name:
        candidates.append(
            LocatorCandidate(
                "role+accessible_name",
                scope.get_by_role(
                    role,  # type: ignore[arg-type]
                    name=field.accessible_name,
                    exact=True,
                ),
            )
        )

    # 4. Associated labels.
    label_candidates = deduplicate_strings([field.accessible_name, *field.labels])
    for label in label_candidates:
        candidates.append(
            LocatorCandidate(
                f"label:{label}",
                scope.get_by_label(label, exact=True),
            )
        )
        normalized = normalize_label(label)
        if normalized and normalized != label:
            candidates.append(
                LocatorCandidate(
                    f"normalized_label:{normalized}",
                    scope.get_by_label(normalized, exact=True),
                )
            )

    # 5. DOM id. Kept below semantic selectors because framework-generated ids
    # can change between page loads.
    if field.element_id:
        candidates.append(
            LocatorCandidate(
                "element_id",
                scope.locator(f"[id={css_string(field.element_id)}]"),
            )
        )

    # 6. Placeholder fallback.
    if field.placeholder:
        candidates.append(
            LocatorCandidate(
                "placeholder",
                scope.get_by_placeholder(field.placeholder, exact=True),
            )
        )

    return candidates


def resolve_frame(page: Page, field: FormField) -> Page | Frame:
    if not field.frame_name and not field.frame_url:
        return page

    matches = [
        frame
        for frame in page.frames
        if (not field.frame_name or frame.name == field.frame_name)
        and (not field.frame_url or frame.url == field.frame_url)
    ]

    if len(matches) != 1:
        raise FieldLocatorError(
            "Could not uniquely resolve iframe: "
            f"name={field.frame_name!r}, url={field.frame_url!r}, "
            f"matches={len(matches)}"
        )

    return matches[0]


def build_form_scope(
    root: Page | Frame,
    field: FormField,
) -> LocatorScope:
    if not field.form_id:
        return root
    return root.locator(f"form[id={css_string(field.form_id)}]")


async def locator_matches_metadata(
    locator: Locator,
    field: FormField,
) -> bool:
    actual = await locator.evaluate(
        """
        element => ({
            tag: element.tagName.toLowerCase(),
            type: element.getAttribute("type"),
            name: element.getAttribute("name"),
            value: element.getAttribute("value")
        })
        """
    )

    if field.tag and actual["tag"] != field.tag.lower():
        return False
    if field.input_type and (
        actual["type"] is None or actual["type"].lower() != field.input_type.lower()
    ):
        return False
    if field.input_name and actual["name"] != field.input_name:
        return False
    if field.option_value is not None and actual["value"] != field.option_value:
        return False

    return True


async def resolve_field_locator(
    page: Page,
    field: FormField,
    *,
    require_visible: bool = True,
    require_enabled: bool = True,
    require_editable: bool = False,
) -> ResolvedField:
    root = resolve_frame(page, field)
    scope = build_form_scope(root, field)

    ambiguous: list[tuple[str, int]] = []
    rejected: list[str] = []

    for candidate in build_locator_candidates(scope, field):
        count = await candidate.locator.count()
        if count == 0:
            continue
        if count > 1:
            ambiguous.append((candidate.strategy, count))
            continue

        locator = candidate.locator
        if not await locator_matches_metadata(locator, field):
            rejected.append(f"{candidate.strategy}: metadata mismatch")
            continue
        if require_visible and not await locator.is_visible():
            rejected.append(f"{candidate.strategy}: not visible")
            continue
        if require_enabled and not await locator.is_enabled():
            rejected.append(f"{candidate.strategy}: not enabled")
            continue
        if require_editable and not await locator.is_editable():
            rejected.append(f"{candidate.strategy}: not editable")
            continue

        return ResolvedField(locator=locator, strategy=candidate.strategy)

    description = (
        field.field_key
        or field.accessible_name
        or field.input_name
        or field.element_id
        or "<unknown>"
    )

    if ambiguous:
        details = ", ".join(f"{strategy}={count}" for strategy, count in ambiguous)
        raise AmbiguousFieldError(f"Field {description!r} matched multiple elements: {details}")

    details = "; ".join(rejected) or "no candidates matched"
    raise FieldNotFoundError(f"Could not resolve field {description!r}: {details}")


__all__ = [
    "AmbiguousFieldError",
    "FieldLocatorError",
    "FieldNotFoundError",
    "ResolvedField",
    "resolve_field_locator",
]
