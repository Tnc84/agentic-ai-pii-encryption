from __future__ import annotations

from collections import defaultdict
import re

from pii.models import PiiSpan


def _canonical(value: str) -> str:
    return value.strip()


def build_alias_map(
    spans: list[PiiSpan],
    existing: dict[str, str] | None = None,
) -> dict[str, str]:
    """Idempotent map: canonical original value -> TOKEN_TYPE_N."""
    alias_map: dict[str, str] = dict(existing or {})
    counters: dict[str, int] = defaultdict(int)

    token_re = re.compile(r"^TOKEN_([A-Z_]+)_(\d+)$")
    for token in alias_map.values():
        match = token_re.match(token)
        if match:
            entity_type, num = match.group(1), int(match.group(2))
            counters[entity_type] = max(counters[entity_type], num)

    for span in sorted(spans, key=lambda s: (s.entity_type, s.start)):
        key = _canonical(span.value)
        if not key or key in alias_map:
            continue
        counters[span.entity_type] += 1
        alias_map[key] = f"TOKEN_{span.entity_type}_{counters[span.entity_type]}"
    return alias_map


def reverse_alias_map(alias_map: dict[str, str]) -> dict[str, str]:
    return {token: original for original, token in alias_map.items()}
