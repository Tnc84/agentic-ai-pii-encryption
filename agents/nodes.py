from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from agents.llm import llm_detect_soft, llm_rewrite, llm_verify
from agents.state import PipelineState
from config.settings import get_settings
from crypto.vault import encrypt_alias_map
from db.repositories import AuditLogsRepo, RunsRepo, VaultMapsRepo
from db.session import get_session_factory
from obs.logging_setup import get_logger
from pii.anonymize import anonymize_text
from pii.mapping import build_alias_map
from pii.models import PiiSource, PiiSpan
from pii.presidio_detect import detect_presidio
from pii.regex_detect import detect_regex, merge_spans
from pii.rescan import rescan_text
from services.report import build_report, write_report_artifacts, write_vault_id

logger = get_logger(__name__)


def _audit(run_id: str, node: str, duration_ms: int, payload: dict[str, Any] | None = None) -> None:
    try:
        session = get_session_factory()()
        try:
            AuditLogsRepo(session).add(
                run_id=run_id,
                node_name=node,
                duration_ms=duration_ms,
                payload=payload,
            )
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_log_failed", node=node, error=str(exc))


def _timed(state: PipelineState, node: str, started: float) -> None:
    duration = int((time.perf_counter() - started) * 1000)
    timings = dict(state.get("node_timings") or {})
    timings[node] = duration
    state["node_timings"] = timings


def ingest_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    state["status"] = "ingested"
    _timed(state, "ingest", started)
    _audit(state["run_id"], "ingest", state["node_timings"]["ingest"], {"chars": len(state.get("raw_text", ""))})
    return state


def detect_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    settings = get_settings()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    text = state["raw_text"]
    allowed = settings.entity_types()
    errors = list(state.get("errors") or [])

    regex_spans: list[PiiSpan] = []
    presidio_spans: list[PiiSpan] = []
    regex_ms = 0
    presidio_ms = 0

    def _run_regex() -> tuple[list[PiiSpan], int]:
        t0 = time.perf_counter()
        spans = detect_regex(text, allowed_types=allowed)
        return spans, int((time.perf_counter() - t0) * 1000)

    def _run_presidio() -> tuple[list[PiiSpan], int, str | None]:
        if not settings.presidio_enabled:
            return [], 0, None
        t0 = time.perf_counter()
        try:
            spans = detect_presidio(
                text,
                allowed_types=allowed,
                language=settings.presidio_language,
            )
            return spans, int((time.perf_counter() - t0) * 1000), None
        except Exception as exc:  # noqa: BLE001
            return [], int((time.perf_counter() - t0) * 1000), f"detect_presidio:{exc}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_regex = pool.submit(_run_regex)
        fut_presidio = pool.submit(_run_presidio)
        regex_spans, regex_ms = fut_regex.result()
        presidio_spans, presidio_ms, presidio_err = fut_presidio.result()

    if presidio_err:
        errors.append(presidio_err)
        logger.warning("detect_presidio_failed", error=presidio_err)

    llm_spans: list[PiiSpan] = []
    llm_usage: dict[str, int] = {}
    soft_types = [t for t in allowed if t in {"PERSON", "ADDRESS"}]
    if settings.llm_soft_detect_enabled and soft_types:
        try:
            detected, llm_usage = llm_detect_soft(text)
            for ent in detected:
                et = ent.entity_type.upper()
                if et not in soft_types:
                    continue
                if ent.start < 0 or ent.end > len(text) or ent.start >= ent.end:
                    continue
                value = text[ent.start : ent.end]
                llm_spans.append(
                    PiiSpan(
                        entity_type=et,
                        start=ent.start,
                        end=ent.end,
                        value=value,
                        confidence=float(ent.confidence),
                        source=PiiSource.LLM,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"detect_llm:{exc}")
            logger.warning("detect_llm_failed", error=str(exc))

    merged = merge_spans(merge_spans(regex_spans, presidio_spans), llm_spans)
    state["errors"] = errors
    state["pii_spans"] = merged
    state["status"] = "detected"
    wall_ms = int((time.perf_counter() - started) * 1000)
    _timed(state, "detect", started)
    payload: dict[str, Any] = {
        "regex_count": len(regex_spans),
        "presidio_count": len(presidio_spans),
        "llm_count": len(llm_spans),
        "merged_count": len(merged),
        "by_type": _counts(merged),
        "regex_ms": regex_ms,
        "presidio_ms": presidio_ms,
        "wall_ms": wall_ms,
    }
    if llm_usage:
        payload.update(llm_usage)
    _audit(state["run_id"], "detect", state["node_timings"]["detect"], payload)
    return state


def verify_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    settings = get_settings()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    spans = list(state.get("pii_spans") or [])
    text = state["raw_text"]
    usage: dict[str, int] = {}

    candidates = [
        {
            "index": i,
            "entity_type": s.entity_type,
            "value": s.value,
            "start": s.start,
            "end": s.end,
            "confidence": s.confidence,
            "source": s.source.value,
        }
        for i, s in enumerate(spans)
    ]

    verified: list[PiiSpan] = []
    rejected: list[PiiSpan] = []
    escalate = False

    if not spans:
        state["verified_spans"] = []
        state["rejected_spans"] = []
        state["escalate"] = False
        state["status"] = "verified"
        _timed(state, "verify", started)
        _audit(state["run_id"], "verify", state["node_timings"]["verify"], {"count": 0})
        return state

    try:
        verdicts, usage = llm_verify(text, candidates)
        by_index = {v.index: v for v in verdicts}
    except Exception as exc:  # noqa: BLE001
        by_index = {}
        errors = list(state.get("errors") or [])
        errors.append(f"verify_llm:{exc}")
        state["errors"] = errors
        logger.warning("verify_llm_failed", error=str(exc))

    for i, span in enumerate(spans):
        verdict = by_index.get(i)
        conf = float(verdict.confidence) if verdict else span.confidence
        keep = True if verdict is None else bool(verdict.keep)
        span.confidence = conf
        if not keep:
            rejected.append(span)
            continue
        if settings.escalate_on_low_confidence and conf < settings.pii_confidence_threshold:
            escalate = True
        verified.append(span)

    if _has_overlap_conflicts(verified):
        escalate = True

    if state.get("force"):
        escalate = False

    state["verified_spans"] = verified
    state["rejected_spans"] = rejected
    state["escalate"] = escalate
    state["status"] = "verified"
    _timed(state, "verify", started)
    payload = {
        "verified": len(verified),
        "rejected": len(rejected),
        "escalate": escalate,
    }
    if usage:
        payload.update(usage)
    _audit(state["run_id"], "verify", state["node_timings"]["verify"], payload)
    return state


def escalate_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    state["status"] = "escalated"
    out_dir = Path(state.get("out_dir") or get_settings().artifacts_dir) / state["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": state["run_id"],
        "escalate": True,
        "spans": [s.safe_dict() for s in state.get("verified_spans") or []],
        "rejected": [s.safe_dict() for s in state.get("rejected_spans") or []],
    }
    (out_dir / "escalation.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    session = get_session_factory()()
    try:
        RunsRepo(session).update_status(state["run_id"], status="escalated", escalate=True)
    finally:
        session.close()
    _timed(state, "escalate", started)
    _audit(state["run_id"], "escalate", state["node_timings"]["escalate"], {"written": True})

    resume_payload = interrupt({"reason": "escalated", "run_id": state["run_id"]})
    if isinstance(resume_payload, dict) and resume_payload.get("force"):
        state["force"] = True
    state["escalate"] = False
    state["status"] = "resume_approved"
    return state


def build_map_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    spans = list(state.get("verified_spans") or [])
    state["alias_map"] = build_alias_map(spans, existing=dict(state.get("alias_map") or {}))
    state["status"] = "mapped"
    _timed(state, "build_map", started)
    _audit(
        state["run_id"],
        "build_map",
        state["node_timings"]["build_map"],
        {"map_size": len(state["alias_map"])},
    )
    return state


def anonymize_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    base_text = (
        state.get("rewritten_text")
        or state.get("anonymized_text")
        or state["raw_text"]
    )
    existing_map = dict(state.get("alias_map") or {})
    text = anonymize_text(
        base_text,
        list(state.get("verified_spans") or []),
        existing_map,
    )
    state["anonymized_text"] = text
    state["status"] = "anonymized"
    _timed(state, "anonymize", started)
    _audit(state["run_id"], "anonymize", state["node_timings"]["anonymize"], {"chars": len(text)})
    return state


def rewrite_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    anonymized = state.get("anonymized_text") or ""
    usage: dict[str, int] = {}
    try:
        rewritten, usage = llm_rewrite(anonymized)
    except Exception as exc:  # noqa: BLE001
        rewritten = anonymized
        errors = list(state.get("errors") or [])
        errors.append(f"rewrite_llm:{exc}")
        state["errors"] = errors
        logger.warning("rewrite_llm_failed", error=str(exc))
    state["rewritten_text"] = rewritten
    state["status"] = "rewritten"
    _timed(state, "rewrite", started)
    payload: dict[str, Any] = {"chars": len(rewritten)}
    if usage:
        payload.update(usage)
    _audit(state["run_id"], "rewrite", state["node_timings"]["rewrite"], payload)
    return state


def rescan_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    settings = get_settings()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    text = state.get("rewritten_text") or state.get("anonymized_text") or ""
    residual = rescan_text(text, allowed_types=settings.entity_types())
    rescan_count = int(state.get("rescan_count") or 0)

    if residual and rescan_count < settings.max_rescan_retries:
        state["rescan_count"] = rescan_count + 1
        state["status"] = "rescan_retry"
        state["pii_spans"] = residual
        state["verified_spans"] = residual
    elif residual:
        state["status"] = "failed_residual_pii"
        errors = list(state.get("errors") or [])
        errors.append("residual_pii_after_rescan")
        state["errors"] = errors
    else:
        state["status"] = "rescan_clean"

    _timed(state, "rescan", started)
    _audit(
        state["run_id"],
        "rescan",
        state["node_timings"]["rescan"],
        {
            "residual": len(residual),
            "rescan_count": state.get("rescan_count", 0),
            "status": state["status"],
        },
    )
    return state


def report_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    settings = get_settings()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    verified = list(state.get("verified_spans") or [])
    rejected = list(state.get("rejected_spans") or [])
    report = build_report(
        run_id=state["run_id"],
        source_path=state.get("source_path"),
        verified=verified,
        rejected=rejected,
        escalate=bool(state.get("escalate")),
        status=state.get("status"),
        node_timings=state.get("node_timings"),
        errors=list(state.get("errors") or []),
        vault_id=state.get("vault_id") or None,
    )
    state["report"] = report
    out_dir = Path(state.get("out_dir") or settings.artifacts_dir) / state["run_id"]
    rewritten = state.get("rewritten_text") or state.get("anonymized_text") or ""
    write_report_artifacts(out_dir=out_dir, report=report, rewritten_text=rewritten)
    state["status"] = "reported"
    _timed(state, "report", started)
    _audit(
        state["run_id"],
        "report",
        state["node_timings"]["report"],
        {"entity_counts": report["entity_counts"]},
    )
    return state


def seal_vault_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["step_count"] = int(state.get("step_count") or 0) + 1
    alias_map = dict(state.get("alias_map") or {})
    salt, nonce, ciphertext = encrypt_alias_map(alias_map)
    session = get_session_factory()()
    try:
        vault = VaultMapsRepo(session).save(
            run_id=state["run_id"],
            salt=salt,
            nonce=nonce,
            ciphertext=ciphertext,
        )
        RunsRepo(session).update_status(state["run_id"], status="completed", escalate=False)
        vault_id = vault.id
    finally:
        session.close()

    state["vault_id"] = vault_id
    state["alias_map"] = {}
    report = dict(state.get("report") or {})
    report["vault_id"] = vault_id
    state["report"] = report

    out_dir = Path(state.get("out_dir") or get_settings().artifacts_dir) / state["run_id"]
    write_vault_id(out_dir, vault_id, report)

    state["status"] = "completed"
    _timed(state, "seal_vault", started)
    _audit(state["run_id"], "seal_vault", state["node_timings"]["seal_vault"], {"vault_id": vault_id})
    return state


def fail_node(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    state["status"] = "failed"
    session = get_session_factory()()
    try:
        RunsRepo(session).update_status(state["run_id"], status="failed")
    finally:
        session.close()
    _timed(state, "fail", started)
    _audit(state["run_id"], "fail", state["node_timings"]["fail"], {"errors": state.get("errors") or []})
    return state


def _counts(spans: list[PiiSpan]) -> dict[str, int]:
    out: dict[str, int] = {}
    for span in spans:
        out[span.entity_type] = out.get(span.entity_type, 0) + 1
    return out


def _has_overlap_conflicts(spans: list[PiiSpan]) -> bool:
    ordered = sorted(spans, key=lambda s: s.start)
    for i in range(len(ordered) - 1):
        if ordered[i].end > ordered[i + 1].start:
            return True
    return False
