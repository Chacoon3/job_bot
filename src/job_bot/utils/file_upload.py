import io

from pypdf import PdfReader


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
