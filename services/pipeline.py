from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.types import Command

from agents.graph import get_compiled_graph
from agents.nodes import detect_node, ingest_node, verify_node
from agents.state import PipelineState
from config.settings import get_settings
from db.migrate import ensure_migrated
from db.repositories import RunsRepo
from db.session import get_session_factory
from obs.logging_setup import bind_run_id, get_logger
from services.ingest import ingest_text

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    run_id: str
    status: str
    escalate: bool = False
    vault_id: str | None = None
    report: dict[str, Any] = field(default_factory=dict)
    out_dir: str | None = None
    errors: list[str] = field(default_factory=list)
    interrupted: bool = False


def ensure_db() -> None:
    ensure_migrated()


def _thread_config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def run_pipeline(
    source: str | Path,
    *,
    out_dir: str | Path | None = None,
    force: bool = False,
) -> PipelineResult:
    settings = get_settings()
    ensure_db()
    source_path, text = ingest_text(source, settings.max_input_chars)

    session = get_session_factory()()
    try:
        run = RunsRepo(session).create(source_path=source_path, model_id=settings.llm_model)
        run_id = run.id
    finally:
        session.close()

    bind_run_id(run_id)
    artifacts = Path(out_dir) if out_dir else Path(settings.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)

    initial: PipelineState = {
        "run_id": run_id,
        "source_path": source_path,
        "raw_text": text,
        "pii_spans": [],
        "verified_spans": [],
        "rejected_spans": [],
        "alias_map": {},
        "anonymized_text": "",
        "rewritten_text": "",
        "report": {},
        "vault_id": "",
        "escalate": False,
        "force": force,
        "errors": [],
        "step_count": 0,
        "rescan_count": 0,
        "status": "started",
        "node_timings": {},
        "out_dir": str(artifacts),
    }

    graph = get_compiled_graph()
    config = _thread_config(run_id)
    final_state: PipelineState = graph.invoke(initial, config=config)
    snapshot = graph.get_state(config)
    interrupted = bool(snapshot.next)

    status = str(final_state.get("status") or "unknown")
    escalate = bool(final_state.get("escalate")) or (
        interrupted and status in {"escalated", "resume_approved"}
    )
    if interrupted and status == "escalated":
        escalate = True

    return PipelineResult(
        run_id=run_id,
        status=status if not interrupted else "escalated",
        escalate=escalate or interrupted,
        vault_id=final_state.get("vault_id") or None,
        report=dict(final_state.get("report") or {}),
        out_dir=str(artifacts / run_id),
        errors=list(final_state.get("errors") or []),
        interrupted=interrupted,
    )


def resume_pipeline(run_id: str, *, force: bool = True) -> PipelineResult:
    """Resume after escalate interrupt (human approval)."""
    ensure_db()
    bind_run_id(run_id)
    graph = get_compiled_graph()
    config = _thread_config(run_id)
    snapshot = graph.get_state(config)
    if not snapshot.next:
        raise ValueError(f"No interrupted run to resume for run_id={run_id}")

    final_state: PipelineState = graph.invoke(
        Command(resume={"force": force}),
        config=config,
    )
    settings = get_settings()
    out = Path(final_state.get("out_dir") or settings.artifacts_dir) / run_id
    return PipelineResult(
        run_id=run_id,
        status=str(final_state.get("status") or "unknown"),
        escalate=False,
        vault_id=final_state.get("vault_id") or None,
        report=dict(final_state.get("report") or {}),
        out_dir=str(out),
        errors=list(final_state.get("errors") or []),
        interrupted=False,
    )


def run_detect_only(source: str | Path) -> PipelineResult:
    """Detect + verify only; no vault, no rewrite."""
    settings = get_settings()
    ensure_db()
    source_path, text = ingest_text(source, settings.max_input_chars)

    session = get_session_factory()()
    try:
        run = RunsRepo(session).create(source_path=source_path, model_id=settings.llm_model)
        run_id = run.id
    finally:
        session.close()

    bind_run_id(run_id)
    state: PipelineState = {
        "run_id": run_id,
        "source_path": source_path,
        "raw_text": text,
        "force": True,
        "errors": [],
        "step_count": 0,
        "node_timings": {},
        "out_dir": settings.artifacts_dir,
    }
    state = ingest_node(state)
    state = detect_node(state)
    state = verify_node(state)

    session = get_session_factory()()
    try:
        status = "escalated" if state.get("escalate") else "detected"
        RunsRepo(session).update_status(run_id, status=status, escalate=bool(state.get("escalate")))
    finally:
        session.close()

    report: dict[str, Any] = {
        "run_id": run_id,
        "source_path": source_path,
        "verified": [s.safe_dict() for s in state.get("verified_spans") or []],
        "rejected": [s.safe_dict() for s in state.get("rejected_spans") or []],
        "escalate": bool(state.get("escalate")),
        "entity_counts": {},
    }
    for span in state.get("verified_spans") or []:
        report["entity_counts"][span.entity_type] = (
            report["entity_counts"].get(span.entity_type, 0) + 1
        )

    out = Path(settings.artifacts_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "detect_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return PipelineResult(
        run_id=run_id,
        status=str(state.get("status") or "detected"),
        escalate=bool(state.get("escalate")),
        report=report,
        out_dir=str(out),
        errors=list(state.get("errors") or []),
    )
