from abc import ABC, abstractmethod

from playwright.async_api import expect
from structlog import get_logger
from structlog.contextvars import bind_contextvars, unbind_contextvars

from job_bot.agent.dropdown_regulator import get_dropdown_regulator_by_field_key
from job_bot.agent.file_upload import upload_greenhouse_cover_letter, upload_greenhouse_resume
from job_bot.agent.filler_tools import (
    fill_text_field,
    locate_by_accessible_name,
    select_dropdown_option,
)
from job_bot.schemas import ApplicationFileSet, FormField, PageInspection, User
from job_bot.utils.browser_tools import BrowserSession


class BaseApplier(ABC):
    def __init__(
        self,
        browser_session: BrowserSession,
        user: User,
        page_inspections: list[PageInspection],
        file_set: ApplicationFileSet | None = None,
    ) -> None:
        self.browser_session = browser_session
        self.user = user
        self.file_set = file_set
        self.page_inspection = page_inspections

    @abstractmethod
    async def fill(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def select_native(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def select_combobox(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def select_radio(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def toggle_checkbox(self, field: FormField, value: bool) -> None: ...

    @abstractmethod
    async def upload_file(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def click(self, field: FormField) -> None: ...

    @abstractmethod
    async def fill_contenteditable(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def pick_date(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def apply(self) -> None: ...


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

    async def apply(self) -> None:

        for field in self.page_inspection[0].form_fields:
            try:
                bind_contextvars(
                    field_key=field.field_key,
                    accessible_name=field.accessible_name,
                    interaction_kind=field.interaction_strategy,
                    input_type=field.input_type,
                )

                if field.field_key == "application-irrelevant":
                    get_logger().info("Skipping irrelevant field")
                    continue

                filler = getattr(self, field.interaction_strategy, None)
                if filler is None:
                    raise ValueError("No filler found for interaction kind.")
                answer = self.user.get_answer(field.field_key)
                if answer is None:
                    raise ValueError("No answer found for field key")
                await filler(field, answer)
                get_logger().info("Field filled successfully", field_value=str(answer)[:5])
            except Exception as e:
                get_logger().error("Error filling field", error=str(e))
            finally:
                unbind_contextvars("field_key", "accessible_name", "interaction_kind", "input_type")
