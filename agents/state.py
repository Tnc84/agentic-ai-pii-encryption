from __future__ import annotations

from typing import Any, TypedDict

from pii.models import PiiSpan


class PipelineState(TypedDict, total=False):
    run_id: str
    source_path: str
    raw_text: str
    pii_spans: list[PiiSpan]
    verified_spans: list[PiiSpan]
    rejected_spans: list[PiiSpan]
    alias_map: dict[str, str]
    anonymized_text: str
    rewritten_text: str
    report: dict[str, Any]
    vault_id: str
    escalate: bool
    force: bool
    errors: list[str]
    step_count: int
    rescan_count: int
    status: str
    node_timings: dict[str, int]
    out_dir: str
