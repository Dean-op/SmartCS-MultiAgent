import pytest

from ecommerce_ai_agent.pdf_ingestion import PdfIngestionError, extract_pdf_markdown


def text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(body)


def test_pdf_extraction_converts_pages_to_markdown() -> None:
    result = extract_pdf_markdown(text_pdf("Refund policy seven days"), "Refund Policy.pdf")

    assert result.title == "Refund Policy"
    assert result.source == "refund-policy.pdf"
    assert result.pages == 1
    assert "# Refund Policy" in result.content
    assert "## Page 1" in result.content
    assert "Refund policy seven days" in result.content


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"not-a-pdf", "pdf_invalid"),
        (text_pdf(""), "pdf_no_extractable_text"),
    ],
)
def test_pdf_extraction_rejects_invalid_or_textless_files(content: bytes, code: str) -> None:
    with pytest.raises(PdfIngestionError) as captured:
        extract_pdf_markdown(content, "policy.pdf")

    assert captured.value.code == code


def test_pdf_extraction_enforces_upload_size_before_parsing() -> None:
    with pytest.raises(PdfIngestionError) as captured:
        extract_pdf_markdown(b"%PDF" + b"x" * 100, "large.pdf", max_bytes=50)

    assert captured.value.code == "pdf_too_large"
