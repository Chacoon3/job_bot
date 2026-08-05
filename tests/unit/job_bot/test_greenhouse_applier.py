from job_bot.agent.greenhouse_applier import _has_correct_value
from job_bot.schemas import FormField, FormOption, InspectedFile, UploadableFile


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


def test_has_correct_value_canonicalizes_current_dropdown_value() -> None:
    field = _field(
        tag="select",
        field_key="country",
        interaction_strategy="select_native",
        current_value="US",
    )

    assert _has_correct_value(field, "United States")
    assert not _has_correct_value(field, "United Kingdom")


def test_has_correct_value_accepts_selected_location_for_city() -> None:
    field = _field(
        role="combobox",
        field_key="city",
        interaction_strategy="select_combobox",
        current_value="New York, New York, United States",
    )

    assert _has_correct_value(field, "New York")
    assert not _has_correct_value(field, "York")


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


def test_has_correct_value_compares_uploaded_file_content() -> None:
    expected = UploadableFile(
        filename="expected.pdf",
        content=b"same PDF bytes",
        mime_type="application/pdf",
    )
    field = _field(
        field_key="attach_resume_button",
        interaction_strategy="upload_file",
        input_type="file",
        current_value=r"C:\fakepath\different-name.pdf",
        uploaded_file=InspectedFile(
            filename="different-name.pdf",
            content=b"same PDF bytes",
            mime_type="application/pdf",
            size=14,
        ),
    )

    assert _has_correct_value(field, expected)


def test_has_correct_value_rejects_missing_or_different_uploaded_content() -> None:
    expected = UploadableFile(
        filename="resume.pdf",
        content=b"expected bytes",
        mime_type="application/pdf",
    )
    missing = _field(
        field_key="attach_resume_button",
        interaction_strategy="upload_file",
        input_type="file",
    )
    different = missing.model_copy(
        update={
            "uploaded_file": InspectedFile(
                filename="resume.pdf",
                content=b"different bytes",
                mime_type="application/pdf",
                size=15,
            )
        }
    )

    assert not _has_correct_value(missing, expected)
    assert not _has_correct_value(different, expected)


def test_has_correct_value_rejects_missing_required_upload() -> None:
    field = _field(
        field_key="attach_resume_button",
        interaction_strategy="upload_file",
        input_type="file",
        required=True,
    )

    assert not _has_correct_value(field, None)
