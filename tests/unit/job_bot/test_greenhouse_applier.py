from job_bot.agent.greenhouse_applier import _has_correct_value
from job_bot.schemas import FormField, FormOption


def _field(**overrides: object) -> FormField:
    values: dict[str, object] = {
        "tag": "input",
        "field_key": "first_name",
        "interaction_strategy": "fill",
    }
    values.update(overrides)
    return FormField(**values)


def test_has_correct_value_requires_the_rendered_value_to_match() -> None:
    assert _has_correct_value(_field(current_value="Ada"), "Ada")
    assert not _has_correct_value(_field(current_value="Grace"), "Ada")
    assert not _has_correct_value(_field(current_value=None), "Ada")


def test_has_correct_value_compares_phone_numbers_in_canonical_format() -> None:
    field = _field(field_key="phone", input_type="tel", current_value="212-555-0198")

    assert _has_correct_value(field, "(212) 555-0198")
    assert _has_correct_value(field, "2125550198")
    assert not _has_correct_value(field, "2125550199")


def test_has_correct_value_ignores_non_application_elements() -> None:
    field = _field(field_key="application-irrelevant", current_value=None)

    assert _has_correct_value(field, None)


def test_has_correct_value_ignores_action_buttons_without_values() -> None:
    field = _field(
        tag="button",
        field_key="submit_button",
        interaction_strategy="click",
        current_value=None,
    )

    assert _has_correct_value(field, None)


def test_has_correct_value_checks_the_selected_dropdown_option_semantically() -> None:
    field = _field(
        tag="select",
        field_key="authorized_to_work",
        interaction_strategy="select_native",
        current_value="1",
        options=[FormOption(label="Yes, I am authorized", value="1", selected=True)],
    )

    assert _has_correct_value(field, "yes")
    assert not _has_correct_value(field, "no")


def test_has_correct_value_checks_boolean_controls() -> None:
    checked = _field(
        field_key="privacy_consent",
        interaction_strategy="toggle_checkbox",
        input_type="checkbox",
        checked=True,
        current_value=True,
    )

    assert _has_correct_value(checked, True)
    assert not _has_correct_value(checked, False)
