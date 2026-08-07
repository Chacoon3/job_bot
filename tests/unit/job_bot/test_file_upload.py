import asyncio
import io
from types import SimpleNamespace
from unittest.mock import Mock

from starlette.datastructures import Headers, UploadFile

from job_bot.utils.file_tools import extract_uploadable_file, parse_pure_text_pdf


def test_parse_pure_text_pdf_concatenates_page_text(monkeypatch) -> None:
    captured_input = {}

    def fake_pdf_reader(pdf_file):
        captured_input["bytes"] = pdf_file.getvalue()
        return pdf_reader

    pdf_reader = Mock()
    pdf_reader.pages = [
        SimpleNamespace(extract_text=Mock(return_value="Hello ")),
        SimpleNamespace(extract_text=Mock(return_value=None)),
        SimpleNamespace(extract_text=Mock(return_value="world")),
    ]
    pdf_reader_factory = Mock(side_effect=fake_pdf_reader)
    monkeypatch.setattr("job_bot.utils.file_tools.PdfReader", pdf_reader_factory)

    result = parse_pure_text_pdf(b"pdf-bytes")

    assert result == "Hello world"
    pdf_reader_factory.assert_called_once()
    assert captured_input["bytes"] == b"pdf-bytes"


def test_extract_uploadable_file_reads_multipart_file() -> None:
    uploaded_file = UploadFile(
        file=io.BytesIO(b"resume-bytes"),
        filename="resume.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    result = asyncio.run(extract_uploadable_file(uploaded_file))

    assert result.filename == "resume.pdf"
    assert result.content == b"resume-bytes"
    assert result.mime_type == "application/pdf"


def test_extract_uploadable_file_uses_default_mime_type() -> None:
    uploaded_file = UploadFile(file=io.BytesIO(b"data"), filename="resume.bin")

    result = asyncio.run(extract_uploadable_file(uploaded_file))

    assert result.mime_type == "application/octet-stream"


def test_extract_uploadable_file_ignores_missing_file() -> None:
    result = asyncio.run(extract_uploadable_file(None))

    assert result is None
