import io

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from starlette.datastructures import UploadFile


class UploadableFile(BaseModel):
    """A user-provided file that can be uploaded without writing it to disk."""

    model_config = ConfigDict(frozen=True)

    filename: str = Field(min_length=1)
    content: bytes = Field(min_length=1, repr=False)
    mime_type: str = Field(default="application/octet-stream", min_length=1)


async def extract_uploadable_file(
    request: Request, file_key: str = "file"
) -> UploadableFile | None:
    """Extract the file stored under the given ``file_key`` in a multipart FastAPI request."""
    form = await request.form()
    uploaded_file = form.get(file_key)
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
