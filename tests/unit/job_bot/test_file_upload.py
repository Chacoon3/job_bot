import asyncio
import io
from types import SimpleNamespace
from unittest.mock import Mock

from starlette.datastructures import FormData, Headers, UploadFile

from job_bot.utils.file_upload import extract_uploadable_file, parse_pure_text_pdf


class FakeRequest:
    def __init__(self, form: FormData) -> None:
        self._form = form

    async def form(self) -> FormData:
        return self._form


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
    monkeypatch.setattr("job_bot.utils.file_upload.PdfReader", pdf_reader_factory)

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
    request = FakeRequest(FormData([("file", uploaded_file)]))

    result = asyncio.run(extract_uploadable_file(request))

    assert result.filename == "resume.pdf"
    assert result.content == b"resume-bytes"
    assert result.mime_type == "application/pdf"


def test_extract_uploadable_file_uses_default_mime_type() -> None:
    uploaded_file = UploadFile(file=io.BytesIO(b"data"), filename="resume.bin")
    request = FakeRequest(FormData([("file", uploaded_file)]))

    result = asyncio.run(extract_uploadable_file(request))

    assert result.mime_type == "application/octet-stream"


def test_extract_uploadable_file_ignores_non_file_form_field() -> None:
    request = FakeRequest(FormData([("file", "not-a-file")]))

    result = asyncio.run(extract_uploadable_file(request))

    assert result is None
