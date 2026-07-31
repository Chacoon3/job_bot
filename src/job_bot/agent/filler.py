from abc import ABC, abstractmethod

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
