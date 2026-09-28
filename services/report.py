from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.settings import get_settings
from pii.models import PiiSpan


def entity_counts(spans: list[PiiSpan]) -> dict[str, int]:
    out: dict[str, int] = {}
    for span in spans:
        out[span.entity_type] = out.get(span.entity_type, 0) + 1
    return out


def build_report(
    *,
    run_id: str,
    source_path: str | None,
    verified: list[PiiSpan],
    rejected: list[PiiSpan],
    escalate: bool,
    status: str | None,
    node_timings: dict[str, int] | None,
    errors: list[str] | None,
    vault_id: str | None,
    model_id: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "run_id": run_id,
        "source_path": source_path,
        "model_id": model_id or settings.llm_model,
        "entity_counts": entity_counts(verified),
        "verified_count": len(verified),
        "rejected_count": len(rejected),
        "escalate": escalate,
        "status": status,
        "node_timings_ms": node_timings or {},
        "errors": errors or [],
        "vault_id": vault_id,
        "spans_safe": [s.safe_dict() for s in verified],
    }


def write_report_artifacts(
    *,
    out_dir: Path,
    report: dict[str, Any],
    rewritten_text: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "rewritten.txt").write_text(rewritten_text, encoding="utf-8")


def write_vault_id(out_dir: Path, vault_id: str, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vault_id.txt").write_text(vault_id, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
