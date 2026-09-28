from __future__ import annotations

from pathlib import Path

from docx import Document
from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


class IngestError(ValueError):
    pass


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise IngestError(
            f"No extractable text in PDF {path} (scan-only PDFs are not supported)"
        )
    return text


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs).strip()
    if not text:
        raise IngestError(f"No extractable text in DOCX {path}")
    return text


def ingest_text(source: str | Path, max_chars: int) -> tuple[str, str]:
    """Return (source_path_label, text). source may be a path or '-' for stdin."""
    if str(source) == "-":
        import sys

        text = sys.stdin.read()
        label = "stdin"
    else:
        path = Path(source)
        if not path.exists() or not path.is_file():
            raise IngestError(f"File not found: {path}")
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise IngestError(
                f"Unsupported file type {path.suffix!r}; allowed: {sorted(SUPPORTED_SUFFIXES)}"
            )
        if suffix == ".pdf":
            text = _read_pdf(path)
        elif suffix == ".docx":
            text = _read_docx(path)
        else:
            text = path.read_text(encoding="utf-8")
        label = str(path.resolve())

    if not text.strip():
        raise IngestError("Input text is empty")
    if len(text) > max_chars:
        raise IngestError(
            f"Input length {len(text)} exceeds MAX_INPUT_CHARS={max_chars}"
        )
    return label, text
