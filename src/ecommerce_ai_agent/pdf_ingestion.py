import re
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfIngestionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PdfExtraction:
    title: str
    source: str
    content: str
    pages: int


def extract_pdf_markdown(
    content: bytes,
    filename: str,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    max_pages: int = 100,
    max_characters: int = 100_000,
) -> PdfExtraction:
    if len(content) > max_bytes:
        raise PdfIngestionError("pdf_too_large")
    if not content.startswith(b"%PDF-"):
        raise PdfIngestionError("pdf_invalid")
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise PdfIngestionError("pdf_encrypted")
        if len(reader.pages) > max_pages:
            raise PdfIngestionError("pdf_too_many_pages")
        pages = [
            " ".join((page.extract_text() or "").replace("\x00", " ").split())
            for page in reader.pages
        ]
    except PdfIngestionError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfIngestionError("pdf_invalid") from exc
    if not any(pages):
        raise PdfIngestionError("pdf_no_extractable_text")
    title = Path(filename).stem.strip()[:200] or "PDF Document"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    source = f"{slug or f'document-{sha256(content).hexdigest()[:8]}'}.pdf"
    markdown = f"# {title}\n\n" + "\n\n".join(
        f"## Page {index}\n\n{text}" for index, text in enumerate(pages, start=1) if text
    )
    if len(markdown) > max_characters:
        raise PdfIngestionError("pdf_text_too_large")
    return PdfExtraction(title, source, markdown, len(reader.pages))
