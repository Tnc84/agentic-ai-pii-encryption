from __future__ import annotations

from pii.models import PiiSpan
from pii.regex_detect import detect_regex


def rescan_text(text: str, allowed_types: list[str] | None = None) -> list[PiiSpan]:
    """Fail-closed helper: residual structured PII after anonymize/rewrite."""
    soft = {"PERSON", "ADDRESS"}
    types = [t for t in (allowed_types or []) if t not in soft] or None
    if types is not None and not types:
        types = ["EMAIL", "PHONE", "IBAN", "CNP", "CREDIT_CARD"]
    return detect_regex(text, allowed_types=types)
