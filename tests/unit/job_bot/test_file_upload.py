from types import SimpleNamespace
from unittest.mock import Mock

from job_bot.file_upload import parse_pure_text_pdf


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
    monkeypatch.setattr("job_bot.file_upload.PyPDF2.PdfReader", pdf_reader_factory)

    result = parse_pure_text_pdf(b"pdf-bytes")

    assert result == "Hello world"
    pdf_reader_factory.assert_called_once()
    assert captured_input["bytes"] == b"pdf-bytes"
