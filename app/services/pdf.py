"""PDF text extraction."""

import pdfplumber


def _extract_pdf_text(pdf_file, max_pages=20, max_chars=7000):
    pages_text = []
    total_chars = 0
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages or total_chars >= max_chars:
                break
            t = page.extract_text()
            if t:
                pages_text.append(t)
                total_chars += len(t)
    return "\n".join(pages_text).strip()[:max_chars]
