from __future__ import annotations

import re
from re import Pattern

from pii.models import PiiEntityType, PiiSource, PiiSpan

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}\b",
)
IBAN_RE = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",
)
CNP_RE = re.compile(r"\b[1-8]\d{12}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

_REGEX_DETECTORS: list[tuple[str, Pattern[str], float]] = [
    (PiiEntityType.EMAIL.value, EMAIL_RE, 0.95),
    (PiiEntityType.IBAN.value, IBAN_RE, 0.9),
    (PiiEntityType.CNP.value, CNP_RE, 0.85),
    (PiiEntityType.CREDIT_CARD.value, CREDIT_CARD_RE, 0.8),
    (PiiEntityType.PHONE.value, PHONE_RE, 0.75),
]


def _luhn_ok(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for idx, char in enumerate(reverse):
        n = int(char)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _normalize_card(raw: str) -> str | None:
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) < 13 or len(digits) > 19:
        return None
    if not _luhn_ok(digits):
        return None
    return digits


def _iban_ok(iban: str) -> bool:
    compact = iban.replace(" ", "").upper()
    if len(compact) < 15 or len(compact) > 34:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def detect_regex(text: str, allowed_types: list[str] | None = None) -> list[PiiSpan]:
    allowed = set(allowed_types) if allowed_types else None
    spans: list[PiiSpan] = []

    for entity_type, pattern, confidence in _REGEX_DETECTORS:
        if allowed is not None and entity_type not in allowed:
            continue
        for match in pattern.finditer(text):
            value = match.group(0)
            start, end = match.start(), match.end()

            if entity_type == PiiEntityType.CREDIT_CARD.value:
                normalized = _normalize_card(value)
                if normalized is None:
                    continue
                value = normalized
            elif entity_type == PiiEntityType.IBAN.value:
                if not _iban_ok(value):
                    continue
                value = value.replace(" ", "").upper()
            elif entity_type == PiiEntityType.PHONE.value:
                digits = re.sub(r"[^\d+]", "", value)
                if len(re.sub(r"[^\d]", "", digits)) < 8:
                    continue

            spans.append(
                PiiSpan(
                    entity_type=entity_type,
                    start=start,
                    end=end,
                    value=value,
                    confidence=confidence,
                    source=PiiSource.REGEX,
                )
            )

    return _dedupe_spans(spans)


def _dedupe_spans(spans: list[PiiSpan]) -> list[PiiSpan]:
    spans_sorted = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.confidence))
    result: list[PiiSpan] = []
    for span in spans_sorted:
        overlap = any(not (span.end <= other.start or span.start >= other.end) for other in result)
        if not overlap:
            result.append(span)
    return sorted(result, key=lambda s: s.start)


def merge_spans(regex_spans: list[PiiSpan], llm_spans: list[PiiSpan]) -> list[PiiSpan]:
    return _dedupe_spans([*regex_spans, *llm_spans])
