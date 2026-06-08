"""
Resume parser — converts uploaded PDF or DOCX to plain text.
"""

import io


def parse_resume(file_bytes: bytes, filename: str) -> str:
    """Parse a PDF or DOCX file (as bytes) to plain text. Raises ValueError on unsupported type."""
    name_lower = filename.lower()

    if name_lower.endswith('.pdf'):
        return _parse_pdf(file_bytes)
    elif name_lower.endswith('.docx'):
        return _parse_docx(file_bytes)
    else:
        raise ValueError(f'Unsupported file type: {filename}. Please upload a PDF or DOCX.')


def _parse_pdf(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or '' for page in pdf.pages]
        return '\n'.join(pages).strip()
    except ImportError:
        pass

    # Fallback: PyPDF2
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        texts = [page.extract_text() or '' for page in reader.pages]
        return '\n'.join(texts).strip()
    except ImportError:
        pass

    raise RuntimeError('PDF parsing unavailable — install pdfplumber: pip install pdfplumber')


def _parse_docx(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return '\n'.join(lines)
