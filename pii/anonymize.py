from __future__ import annotations

from pii.models import PiiSpan


def anonymize_text(text: str, spans: list[PiiSpan], alias_map: dict[str, str]) -> str:
    """Replace span values using alias_map; process from end to keep offsets valid."""
    result = text
    for span in sorted(spans, key=lambda s: s.start, reverse=True):
        token = alias_map.get(span.value.strip()) or alias_map.get(span.value)
        if not token:
            continue
        result = result[: span.start] + token + result[span.end :]
    return result


def deanonymize_text(text: str, alias_map: dict[str, str]) -> str:
    reverse = {token: original for original, token in alias_map.items()}
    # Replace longer tokens first to avoid partial collisions
    result = text
    for token in sorted(reverse.keys(), key=len, reverse=True):
        result = result.replace(token, reverse[token])
    return result
