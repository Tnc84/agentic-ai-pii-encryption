from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from agents.nodes import (
    anonymize_node,
    build_map_node,
    detect_node,
    escalate_node,
    fail_node,
    ingest_node,
    report_node,
    rescan_node,
    rewrite_node,
    seal_vault_node,
    verify_node,
)
from agents.state import PipelineState
from config.settings import get_settings

_compiled = None
_checkpointer: SqliteSaver | None = None
_conn: sqlite3.Connection | None = None


def _after_verify(state: PipelineState) -> str:
    if state.get("escalate"):
        return "escalate"
    return "build_map"


def _after_rescan(state: PipelineState) -> str:
    settings = get_settings()
    status = state.get("status")
    if status == "rescan_clean":
        return "report"
    if status == "rescan_retry":
        if int(state.get("step_count") or 0) >= settings.max_graph_steps:
            return "fail"
        return "build_map"
    return "fail"


def get_checkpointer() -> SqliteSaver:
    global _checkpointer, _conn
    if _checkpointer is None:
        path = Path(get_settings().checkpoint_db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _checkpointer = SqliteSaver(_conn)
        _checkpointer.setup()
    return _checkpointer


def build_graph(checkpointer: SqliteSaver | None = None):
    graph = StateGraph(PipelineState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("detect", detect_node)
    graph.add_node("verify", verify_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("build_map", build_map_node)
    graph.add_node("anonymize", anonymize_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("rescan", rescan_node)
    graph.add_node("report", report_node)
    graph.add_node("seal_vault", seal_vault_node)
    graph.add_node("fail", fail_node)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "detect")
    graph.add_edge("detect", "verify")
    graph.add_conditional_edges(
        "verify",
        _after_verify,
        {"escalate": "escalate", "build_map": "build_map"},
    )
    graph.add_edge("escalate", "build_map")
    graph.add_edge("build_map", "anonymize")
    graph.add_edge("anonymize", "rewrite")
    graph.add_edge("rewrite", "rescan")
    graph.add_conditional_edges(
        "rescan",
        _after_rescan,
        {"report": "report", "build_map": "build_map", "fail": "fail"},
    )
    graph.add_edge("report", "seal_vault")
    graph.add_edge("seal_vault", END)
    graph.add_edge("fail", END)
    saver = checkpointer if checkpointer is not None else get_checkpointer()
    return graph.compile(checkpointer=saver)


def get_compiled_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def reset_compiled_graph() -> None:
    global _compiled
    _compiled = None
