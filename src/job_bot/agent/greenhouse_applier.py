import asyncio
import re
from typing import Any

from playwright.async_api import expect
from structlog import get_logger
from structlog.contextvars import bind_contextvars, unbind_contextvars

from job_bot.agent.applier import BaseApplier
from job_bot.agent.applier_agent import (
    agent_fill_interactive_element,
    agent_infer_interactive_element_answer,
)
from job_bot.agent.dropdown_regulator import get_dropdown_regulator_by_field_key
from job_bot.agent.file_upload import upload_greenhouse_cover_letter, upload_greenhouse_resume
from job_bot.agent.filler_tools import (
    build_greenhouse_tools,
    fill_text_field,
    inspect_page,
    locate_by_accessible_name,
    select_dropdown_option,
)
from job_bot.exceptions import IncompleteApplicationError
from job_bot.llm import OpenAILLMProvider
from job_bot.schemas import FormField, JobFormFieldKey, UploadableFile, YesNoOption
from job_bot.utils.browser_tools import BrowserSession
from job_bot.utils.file_tools import is_same_file_content


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

    if field.interaction_strategy == "upload_file":
        if expected_value is None:
            return not field.required
        if not isinstance(expected_value, UploadableFile) or field.uploaded_file is None:
            return False
        return is_same_file_content(
            field.uploaded_file.content,
            expected_value.content,
        )

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

    if field.interaction_strategy in {"select_native", "select_combobox"}:
        actual_values: list[object] = [field.current_value]
        actual_values.extend(
            value
            for option in field.options
            if option.selected
            for value in (option.label, option.value)
        )

        regulator = get_dropdown_regulator_by_field_key(field.field_key)
        if regulator:
            expected_value = regulator(str(expected_value))
            actual_values = [
                regulator(value) if isinstance(value, str) else value for value in actual_values
            ]

        return any(
            actual_value == expected_value
            or (
                isinstance(actual_value, str)
                and actual_value.strip().casefold() == str(expected_value).strip().casefold()
            )
            or (
                field.field_key == "city"
                and isinstance(actual_value, str)
                and actual_value.strip()
                .casefold()
                .startswith(f"{str(expected_value).strip().casefold()},")
            )
            for actual_value in actual_values
        )

    actual_value = field.current_value
    if actual_value == expected_value:
        return True
    if isinstance(actual_value, str):
        if field.field_key == "phone":
            expected_phone = _canonicalize_phone_number(expected_value)
            actual_phone = _canonicalize_phone_number(actual_value)
            if expected_phone and actual_phone == expected_phone:
                return True
        if actual_value.strip().casefold() == str(expected_value).strip().casefold():
            return True

    return False


class GreenHouseFiller(BaseApplier):

    def get_answer(self, field_key: JobFormFieldKey) -> Any:
        """Get the answer for a given field key."""
        if field_key in {"attach_resume_button", "attach_cover_letter_button"}:
            if self.file_set is None:
                return None
            if field_key == "attach_resume_button":
                return self.file_set.resume
            return self.file_set.cover_letter
        return getattr(self.user, field_key, None)

    async def fill(self, field: FormField, value: str) -> None:
        locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )
        await expect(locator).to_be_visible(timeout=5000)
        if field.field_key == "phone":
            await fill_text_field(locator, value, canonicalizer=_canonicalize_phone_number)
        else:
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

        query = value
        if field.field_key == "city":
            await dropdown_locator.click()
            await dropdown_locator.fill(self.user.city)
            await self.browser_session.page().wait_for_timeout(
                1000
            )  # Wait for 1 second to allow the dropdown to open
            await self.browser_session.page().keyboard.press("Tab")
            return
        elif field.field_key == "communications_consent" or field.field_key == "privacy_consent":
            value: YesNoOption = "no"
            query = value

        await select_dropdown_option(
            self.browser_session.page(),
            dropdown_locator,
            value,
            regulator=get_dropdown_regulator_by_field_key(field.field_key),
            query=query,
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

    async def toggle_checkbox(self, field: FormField, value: bool) -> None: ...

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

    async def click(self, field: FormField) -> None:
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

    async def playwright_apply(self, browser_session: BrowserSession) -> None:
        page_inspection = await inspect_page(browser_session.page())

        for field in page_inspection.form_fields:
            try:
                bind_contextvars(
                    field_key=field.field_key,
                    accessible_name=field.accessible_name,
                    interaction_kind=field.interaction_strategy,
                    input_type=field.input_type,
                    field_required=field.required,
                )

                if field.field_key == "application-irrelevant" or field.field_key == "unknown":
                    get_logger().info("Skipping not supported field")
                    continue

                answer = self.get_answer(field.field_key)
                # check if already filled with correct answer
                if _has_correct_value(field, answer):
                    continue

                filler = getattr(self, field.interaction_strategy, None)
                if filler is None:
                    raise ValueError("No filler found for interaction kind.")

                await filler(field, answer)
                get_logger().info("Field filled successfully", field_value=str(answer)[:5])
            except Exception as e:
                get_logger().error("Error filling field", error=str(e)[:100])
            finally:
                unbind_contextvars(
                    "field_key",
                    "accessible_name",
                    "interaction_kind",
                    "input_type",
                    "field_required",
                )

        completed_inspection = await inspect_page(browser_session.page())
        field_correctness = {
            field.accessible_name: (
                _has_correct_value(field, self.get_answer(field.field_key)),
                self.get_answer(field.field_key),
                field.current_value,
            )
            for field in completed_inspection.form_fields
            if field.required is True
        }
        all_fields_filled = all(correctness for correctness, _, _ in field_correctness.values())

        get_logger().debug(
            "application state",
            field_correctness=field_correctness,
            all_fields_filled=all_fields_filled,
        )
        if not all_fields_filled:
            not_filled_fields = [
                accessible_name
                for accessible_name, (correctness, _, _) in field_correctness.items()
                if not correctness
            ]
            raise IncompleteApplicationError(f"Fields not filled: {not_filled_fields}")

    async def llm_resolve_incomplete_application(self, browser_session: BrowserSession) -> None:
        get_logger().info("Attempting to resolve incomplete application using LLM.")
        tools = build_greenhouse_tools(browser_session)
        page_inspection = await inspect_page(browser_session.page())
        fields_to_fill = [
            field
            for field in page_inspection.form_fields
            if not _has_correct_value(field, self.get_answer(field.field_key))
            and field.required is True
        ]

        inferred_answers = await agent_fill_interactive_element(
            OpenAILLMProvider().get_model(), tools, fields_to_fill, self.user
        )
        get_logger().info(
            "LLM field filling completed.",
            requested_field_count=len(fields_to_fill),
            inferred_answer_count=len(inferred_answers.answers),
        )

    async def llm_assist_incomplete_application(self, browser_session: BrowserSession) -> None:
        get_logger().info("Attempting to resolve incomplete application using LLM (assisted).")
        tools = build_greenhouse_tools(browser_session, "read")
        page_inspection = await inspect_page(browser_session.page())
        fields_to_fill = [
            field
            for field in page_inspection.form_fields
            if not _has_correct_value(field, self.get_answer(field.field_key))
            and field.required is True
        ]

        inferred_answers = await agent_infer_interactive_element_answer(
            OpenAILLMProvider().get_model(), tools, fields_to_fill, self.user
        )
        answers_by_field_key = {
            suggestion.field_key: suggestion.value for suggestion in inferred_answers.answers
        }

        for field in fields_to_fill:
            try:
                bind_contextvars(
                    field_key=field.field_key,
                    accessible_name=field.accessible_name,
                    interaction_kind=field.interaction_strategy,
                    input_type=field.input_type,
                    field_required=field.required,
                )

                if field.field_key not in answers_by_field_key:
                    get_logger().warning("No inferred answer returned for field.")
                    continue

                answer = answers_by_field_key[field.field_key]
                if answer is None:
                    get_logger().warning("Inferred answer is empty; skipping field.")
                    continue

                filler = getattr(self, field.interaction_strategy, None)
                if filler is None:
                    raise ValueError("No filler found for interaction kind.")

                await filler(field, answer)
                get_logger().info("Field filled successfully", field_value=str(answer)[:5])
            except Exception as e:
                get_logger().error("Error filling field", error=str(e)[:100])
            finally:
                unbind_contextvars(
                    "field_key",
                    "accessible_name",
                    "interaction_kind",
                    "input_type",
                    "field_required",
                )

    async def apply(self) -> None:

        async with self.browser_session as browser_session:
            page = browser_session.page()

            await page.goto(self.job_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            try:
                await self.playwright_apply(browser_session)
            except IncompleteApplicationError as e:
                get_logger().warning("Incomplete application detected", error=str(e))
                await self.llm_assist_incomplete_application(browser_session)

            await asyncio.sleep(30)  # Wait for 3 seconds before final inspection
