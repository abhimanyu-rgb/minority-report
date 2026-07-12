"""Extract plain text from uploaded BRD/idea files.

Supports: .pdf, .docx, .txt, .md. 10 MB hard cap. Decode failures raise
ExtractError with a user-facing message; the endpoint surfaces it as 400.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

MAX_BYTES = 10 * 1024 * 1024  # 10 MB

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
SUPPORTED_MIMETYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}


class ExtractError(Exception):
    """Raised when extraction fails for a reason the user should see."""


@dataclass
class Extracted:
    text: str
    char_count: int
    source_kind: str  # "pdf" | "docx" | "text"
    pages: int | None = None  # only meaningful for PDFs


def _ext(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def extract(data: bytes, filename: str, content_type: str | None = None) -> Extracted:
    """Dispatch to the right extractor based on file extension."""
    if len(data) == 0:
        raise ExtractError("Uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise ExtractError(
            f"File is {len(data) / 1_048_576:.1f} MB; the limit is {MAX_BYTES // 1_048_576} MB."
        )

    ext = _ext(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        # Fall back to mimetype if the filename is uninformative.
        if content_type not in SUPPORTED_MIMETYPES:
            raise ExtractError(
                f"Unsupported file type {ext or content_type or 'unknown'!r}. "
                f"Accepted: PDF, DOCX, TXT, MD."
            )
        # Best-effort mapping mimetype -> ext when filename is bad.
        ext = {
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "text/plain": ".txt",
            "text/markdown": ".md",
            "text/x-markdown": ".md",
        }[content_type]

    if ext == ".pdf":
        return _extract_pdf(data)
    if ext == ".docx":
        return _extract_docx(data)
    return _extract_text(data, ext)


def _extract_pdf(data: bytes) -> Extracted:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ExtractError("PDF extractor not installed (pypdf).") from e

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise ExtractError(f"Could not parse PDF: {e}") from e

    if reader.is_encrypted:
        # Try empty password as a courtesy; some PDFs are "encrypted" with no password.
        try:
            reader.decrypt("")
        except Exception:
            raise ExtractError("PDF is password-protected; please remove protection and re-upload.")

    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            # Don't abort the whole document if one page is weird.
            chunks.append("")

    text = _normalize("\n\n".join(chunks))
    if not text.strip():
        raise ExtractError(
            "No selectable text found in this PDF. It may be a scan or image — "
            "export the source document to PDF (or paste the text in directly)."
        )
    return Extracted(text=text, char_count=len(text), source_kind="pdf", pages=len(reader.pages))


def _extract_docx(data: bytes) -> Extracted:
    try:
        from docx import Document
    except ImportError as e:
        raise ExtractError("DOCX extractor not installed (python-docx).") from e

    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:
        raise ExtractError(f"Could not parse DOCX: {e}") from e

    lines: list[str] = []
    for para in doc.paragraphs:
        if para.text:
            lines.append(para.text)
    # Tables — flatten cell text row-wise, tab-separated.
    for table in doc.tables:
        for row in table.rows:
            row_text = "\t".join(cell.text.strip() for cell in row.cells if cell.text)
            if row_text:
                lines.append(row_text)

    text = _normalize("\n".join(lines))
    if not text.strip():
        raise ExtractError("DOCX contains no extractable text.")
    return Extracted(text=text, char_count=len(text), source_kind="docx")


def _extract_text(data: bytes, ext: str) -> Extracted:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = _normalize(data.decode(enc))
            if not text.strip():
                raise ExtractError("Text file is empty after decoding.")
            return Extracted(text=text, char_count=len(text), source_kind="text")
        except UnicodeDecodeError:
            continue
    raise ExtractError("Could not decode text file as UTF-8 or Latin-1.")


def _normalize(text: str) -> str:
    """Strip BOM, normalize line endings, collapse excessive blank lines."""
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ consecutive blank lines down to 2.
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
