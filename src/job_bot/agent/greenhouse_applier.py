import random
import re

from playwright.async_api import expect
from structlog import get_logger
from structlog.contextvars import bind_contextvars, unbind_contextvars

from job_bot.agent.dropdown_regulator import get_dropdown_regulator_by_field_key
from job_bot.agent.file_upload import upload_greenhouse_cover_letter, upload_greenhouse_resume
from job_bot.agent.filler import BaseApplier
from job_bot.agent.filler_tools import (
    fill_text_field,
    inspect_active_page,
    locate_by_accessible_name,
    select_dropdown_option,
)
from job_bot.schemas import FormField


def _canonicalize_phone_number(value: object) -> str:
    """Return the digits used to compare differently formatted phone numbers."""
    return re.sub(r"\D", "", str(value))


def _has_correct_value(field: FormField, expected_value: object) -> bool:
    """Return whether an application field contains its expected answer."""
    if field.field_key == "application-irrelevant":
        return True

    # Buttons trigger actions; unlike form controls, they do not retain values
    # that can be validated as application answers.
    if field.interaction_strategy == "click":
        return True

    if expected_value is None:
        return False

    if field.interaction_strategy in {"select_radio", "toggle_checkbox"}:
        if isinstance(expected_value, bool):
            return field.checked is expected_value

        # A radio control represents one option, so it is correct only when the
        # checked option is the requested one.
        if not field.checked:
            return False
        regulator = get_dropdown_regulator_by_field_key(field.field_key)
        actual_value = field.accessible_name or field.current_value
        if regulator and isinstance(actual_value, str):
            return regulator(actual_value) == regulator(str(expected_value))
        return str(actual_value).strip().casefold() == str(expected_value).strip().casefold()

    actual_values: list[object] = [field.current_value]
    if field.interaction_strategy in {"select_native", "select_combobox"}:
        actual_values.extend(
            value
            for option in field.options
            if option.selected
            for value in (option.label, option.value)
        )

    regulator = get_dropdown_regulator_by_field_key(field.field_key)
    for actual_value in actual_values:
        if actual_value == expected_value:
            return True
        if isinstance(actual_value, str):
            if field.field_key == "phone":
                expected_phone = _canonicalize_phone_number(expected_value)
                actual_phone = _canonicalize_phone_number(actual_value)
                if expected_phone and actual_phone == expected_phone:
                    return True
            if regulator and regulator(actual_value) == regulator(str(expected_value)):
                return True
            if actual_value.strip().casefold() == str(expected_value).strip().casefold():
                return True

    return False


class GreenHouseFiller(BaseApplier):

    async def fill(self, field: FormField, value: str) -> None:
        locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )
        await expect(locator).to_be_visible(timeout=5000)
        await fill_text_field(locator, value)

    async def select_native(self, field: FormField, value: str) -> None:
        dropdown_locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )

        get_logger().info(
            "Filling native dropdown field",
            field_name=field.accessible_name,
            field_value=value,
        )

        await select_dropdown_option(
            self.browser_session.page(),
            dropdown_locator,
            value,
            regulator=get_dropdown_regulator_by_field_key(field.field_key),
        )

    async def select_combobox(self, field: FormField, value: str) -> None:
        dropdown_locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )

        get_logger().info(
            "Filling dropdown field",
            field_name=field.accessible_name,
            field_value=value,
        )

        await select_dropdown_option(
            self.browser_session.page(),
            dropdown_locator,
            value,
            regulator=get_dropdown_regulator_by_field_key(field.field_key),
        )

    async def select_radio(self, field: FormField, value: str) -> None:
        radio_locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )

        get_logger().info(
            "Filling radio field",
            field_name=field.accessible_name,
            field_value=value,
        )

        await radio_locator.check()

    async def toggle_checkbox(self, field: FormField, value: bool) -> None:
        pass

    async def upload_file(self, field: FormField, value: str) -> None:
        if field.field_key == "attach_resume_button":
            if self.file_set.resume is None:
                get_logger().warning("No resume file provided for upload.")
                return
            else:
                await upload_greenhouse_resume(
                    self.browser_session.page(),
                    self.file_set.resume,
                )
        elif field.field_key == "attach_cover_letter_button":
            if self.file_set.cover_letter is None:
                get_logger().warning("No cover letter file provided for upload.")
                return
            else:
                await upload_greenhouse_cover_letter(
                    self.browser_session.page(),
                    self.file_set.cover_letter,
                )

    async def click(self, field: FormField, value: str) -> None:
        button_locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )

        get_logger().info(
            "Clicking button",
            field_name=field.accessible_name,
        )

        await button_locator.click()

    async def fill_contenteditable(self, field: FormField, value: str) -> None:
        pass

    async def pick_date(self, field: FormField, value: str) -> None:
        pass

    async def apply(self) -> None:

        all_fields_filled = False
        max_loop = 3
        while not all_fields_filled and max_loop > 0:
            page_inspection = await inspect_active_page(self.browser_session.page())

            for field in page_inspection.form_fields:
                try:
                    bind_contextvars(
                        field_key=field.field_key,
                        accessible_name=field.accessible_name,
                        interaction_kind=field.interaction_strategy,
                        input_type=field.input_type,
                    )

                    if field.field_key == "application-irrelevant" or field.field_key == "unknown":
                        get_logger().info("Skipping not supported field")
                        continue

                    answer = self.user.get_answer(field.field_key)
                    if answer is None:
                        raise ValueError("No answer found for field key")
                    # check if already filled with correct answer
                    if _has_correct_value(field, answer):
                        continue

                    filler = getattr(self, field.interaction_strategy, None)
                    if filler is None:
                        raise ValueError("No filler found for interaction kind.")

                    await filler(field, answer)
                    get_logger().info("Field filled successfully", field_value=str(answer)[:5])
                except Exception as e:
                    get_logger().error("Error filling field", error=str(e))
                finally:
                    unbind_contextvars(
                        "field_key", "accessible_name", "interaction_kind", "input_type"
                    )

            completed_inspection = await inspect_active_page(self.browser_session.page())
            all_fields_filled = all(
                _has_correct_value(field, self.user.get_answer(field.field_key))
                for field in completed_inspection.form_fields
            )

            await self.browser_session.page().wait_for_timeout(
                random.randint(100, 1500)
            )  # Wait for 1 second before re-inspecting the page
            max_loop -= 1
