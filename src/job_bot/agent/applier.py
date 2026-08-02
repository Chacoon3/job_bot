from abc import ABC, abstractmethod

from playwright.async_api import Playwright

from job_bot.schemas import ApplicationFileSet, FormField, User
from job_bot.utils.browser_tools import BrowserSession


class BaseApplier(ABC):
    def __init__(
        self,
        playwright: Playwright,
        user: User,
        job_url: str,
        file_set: ApplicationFileSet | None = None,
    ) -> None:
        self.playwright = playwright
        self.browser_session = BrowserSession(playwright)
        self.job_url = job_url
        self.user = user
        self.file_set = file_set

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
