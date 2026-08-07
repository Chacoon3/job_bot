import io
from io import BytesIO
from typing import BinaryIO, TypeAlias

from pypdf import PdfReader
from starlette.datastructures import UploadFile

from job_bot.schemas import UploadableFile

FileContent: TypeAlias = bytes | bytearray | memoryview | BinaryIO


async def extract_uploadable_file(uploaded_file: UploadFile | None) -> UploadableFile | None:
    """Convert an uploaded FastAPI file into an application upload value."""
    if not isinstance(uploaded_file, UploadFile):
        return None
    if not uploaded_file.filename:
        return None

    return UploadableFile(
        filename=uploaded_file.filename,
        content=await uploaded_file.read(),
        mime_type=uploaded_file.content_type or "application/octet-stream",
    )


def parse_pure_text_pdf(data: bytes) -> str:
    """
    Parse a PDF file and extract the text content.

    Args:
        data (bytes): The PDF file content as bytes.

    Returns:
        str: The extracted text content from the PDF.
    """
    with io.BytesIO(data) as pdf_file:
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text


def is_same_file_content(
    first: FileContent, second: FileContent, *, chunk_size: int = 1024 * 1024
) -> bool:
    """Check if two in-memory files contain exactly the same bytes."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if first is second:
        return True

    def as_stream(value: FileContent) -> tuple[BinaryIO, int | None]:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return BytesIO(value), None

        if not value.seekable():
            raise ValueError("Binary streams must be seekable")

        original_position = value.tell()
        value.seek(0)
        return value, original_position

    first_stream, first_position = as_stream(first)
    second_stream, second_position = as_stream(second)

    try:
        while True:
            first_chunk = first_stream.read(chunk_size)
            second_chunk = second_stream.read(chunk_size)

            if first_chunk != second_chunk:
                return False

            if not first_chunk:
                return True
    finally:
        if first_position is not None:
            first_stream.seek(first_position)

        if second_position is not None:
            second_stream.seek(second_position)
