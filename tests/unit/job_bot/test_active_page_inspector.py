import asyncio
from unittest.mock import AsyncMock

from job_bot.agent.planned_applier import inspect_active_page


def test_inspect_active_page_builds_validated_form_fields() -> None:
    page = AsyncMock()
    page.evaluate.return_value = [
        {
            "interaction_strategy": "fill",
            "control_kind": "input",
            "element_id": "email",
            "input_name": "email",
            "test_id": None,
            "tag": "input",
            "role": None,
            "input_type": "email",
            "accessible_name": "Email",
            "labels": ["Email*"],
            "placeholder": None,
            "current_value": None,
            "options": [],
            "required": True,
            "visible": True,
            "enabled": True,
            "editable": True,
            "readonly": False,
            "checked": None,
            "multiple": False,
            "form_id": "application-form",
            "group_key": None,
            "group_label": None,
            "component": "standalone",
            "frame_url": "https://example.com/apply",
            "frame_name": None,
        },
        {
            "interaction_strategy": "select_native",
            "control_kind": "select",
            "element_id": "state",
            "input_name": "state",
            "test_id": None,
            "tag": "select",
            "role": None,
            "input_type": None,
            "accessible_name": "State",
            "labels": ["State"],
            "placeholder": None,
            "current_value": "NY",
            "options": [
                {
                    "label": "New York",
                    "value": "NY",
                    "selected": True,
                    "disabled": False,
                }
            ],
            "required": False,
            "visible": True,
            "enabled": True,
            "editable": False,
            "readonly": False,
            "checked": None,
            "multiple": False,
            "form_id": "application-form",
            "group_key": None,
            "group_label": None,
            "component": "standalone",
            "frame_url": "https://example.com/apply",
            "frame_name": None,
        },
    ]

    inspection = asyncio.run(inspect_active_page(page))

    assert len(inspection.form_fields) == 2
    assert inspection.form_fields[0].field_key == "email"
    assert inspection.form_fields[0].input_type == "email"
    assert inspection.form_fields[1].interaction_strategy == "select_native"
    assert inspection.form_fields[1].options[0].label == "New York"
    page.evaluate.assert_awaited_once()


def test_inspect_active_page_identifies_greenhouse_phone_country_combobox() -> None:
    page = AsyncMock()
    page.evaluate.return_value = [
        {
            "interaction_strategy": "select_combobox",
            "control_kind": "input",
            "element_id": "country",
            "input_name": None,
            "test_id": None,
            "tag": "input",
            "role": "combobox",
            "input_type": "text",
            "accessible_name": "Country",
            "labels": ["Country*"],
            "placeholder": None,
            "current_value": None,
            "options": [],
            "required": True,
            "visible": True,
            "enabled": True,
            "editable": True,
            "readonly": False,
            "checked": None,
            "multiple": False,
            "form_id": "application-form",
            "group_key": None,
            "group_label": "Phone",
            "component": "phone_country",
            "frame_url": "https://job-boards.greenhouse.io/example/jobs/1",
            "frame_name": None,
        }
    ]

    inspection = asyncio.run(inspect_active_page(page))
    field = inspection.form_fields[0]

    assert field.field_key == "phone_country"
    assert field.role == "combobox"
    assert field.input_type == "text"
    assert field.element_id == "country"
    assert field.interaction_strategy == "select_combobox"
