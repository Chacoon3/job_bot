from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TypeAlias

from playwright.async_api import (
    Locator,
    Page,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import (
    expect,
)

from job_bot.data.schemas import UploadableFile

FileSource: TypeAlias = str | PathLike[str] | UploadableFile


class FileChooserNotOpenedError(RuntimeError):
    """Raised when clicking an upload trigger does not open a file chooser."""


def _as_playwright_file(file: FileSource) -> str | dict[str, str | bytes]:
    if isinstance(file, UploadableFile):
        if not file.filename.strip():
            raise ValueError("filename must not be empty")
        if not file.mime_type.strip():
            raise ValueError("mime_type must not be empty")

        return {
            "name": file.filename,
            "mimeType": file.mime_type,
            "buffer": file.content,
        }

    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Upload file does not exist: {path}")

    return str(path)


async def click_and_upload_file(
    page: Page,
    upload_trigger: Locator,
    file: FileSource,
    *,
    timeout: float = 5_000,
) -> None:
    """Click an upload control and set the resulting native file chooser.

    ``upload_trigger`` should already be scoped to the intended field. This is
    important on forms that contain several identical "Attach" buttons.

    The file-chooser listener is registered before the click, avoiding the race
    that occurs when code clicks first and starts waiting afterward.
    """
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    playwright_file = _as_playwright_file(file)

    await expect(upload_trigger).to_be_visible(timeout=timeout)
    await expect(upload_trigger).to_be_enabled(timeout=timeout)

    try:
        async with page.expect_file_chooser(timeout=timeout) as chooser_info:
            await upload_trigger.click(timeout=timeout)

        chooser = await chooser_info.value
    except PlaywrightTimeoutError as exc:
        raise FileChooserNotOpenedError(
            "The upload trigger did not open a native file chooser"
        ) from exc

    await chooser.set_files(playwright_file, timeout=timeout)


async def upload_greenhouse_resume(
    page: Page,
    file: FileSource,
    *,
    timeout: float = 5_000,
) -> None:
    """Upload a resume on a Greenhouse form without matching a global button."""
    resume_input = page.locator('input[type="file"]#resume')
    attach_button = resume_input.locator("xpath=preceding-sibling::button[1]")

    await click_and_upload_file(
        page,
        attach_button,
        file,
        timeout=timeout,
    )


async def upload_greenhouse_cover_letter(
    page: Page,
    file: FileSource,
    *,
    timeout: float = 5_000,
) -> None:
    """Upload a cover letter on a Greenhouse form without matching a global button."""
    cover_letter_input = page.locator('input[type="file"]#cover_letter')
    attach_button = cover_letter_input.locator("xpath=preceding-sibling::button[1]")

    await click_and_upload_file(
        page,
        attach_button,
        file,
        timeout=timeout,
    )
