"""Read-only MCP server for runs / audit (no vault decrypt, no plaintext map)."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from db.migrate import ensure_migrated
from db.repositories import AuditLogsRepo, RunsRepo
from db.session import get_session_factory
from obs.logging_setup import configure_logging

configure_logging()
mcp = MCPServer(name="pii-pipeline-readonly")


@mcp.tool()
def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """List recent pipeline runs (metadata only, no PII)."""
    ensure_migrated()
    session = get_session_factory()()
    try:
        rows = RunsRepo(session).list_runs(limit=limit)
        return [
            {
                "id": r.id,
                "source_path": r.source_path,
                "status": r.status,
                "escalate": r.escalate,
                "model_id": r.model_id,
            }
            for r in rows
        ]
    finally:
        session.close()


@mcp.tool()
def get_run(run_id: str) -> dict[str, Any]:
    """Get one run by id (metadata only)."""
    ensure_migrated()
    session = get_session_factory()()
    try:
        run = RunsRepo(session).get(run_id)
        if run is None:
            return {"error": "not_found"}
        return {
            "id": run.id,
            "source_path": run.source_path,
            "status": run.status,
            "escalate": run.escalate,
            "model_id": run.model_id,
        }
    finally:
        session.close()


@mcp.tool()
def get_audit_logs(run_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Audit events for a run (counts/timings only; payloads already PII-free)."""
    ensure_migrated()
    session = get_session_factory()()
    try:
        rows = AuditLogsRepo(session).list_for_run(run_id, limit=limit)
        return [
            {
                "node_name": r.node_name,
                "duration_ms": r.duration_ms,
                "payload": json.loads(r.payload_json or "{}"),
            }
            for r in rows
        ]
    finally:
        session.close()


@mcp.tool()
def get_safe_report(run_id: str) -> dict[str, Any]:
    """Load artifacts/<run_id>/report.json if present (safe report, no plaintext PII)."""
    from pathlib import Path

    from config.settings import get_settings

    path = Path(get_settings().artifacts_dir) / run_id / "report.json"
    if not path.exists():
        return {"error": "report_not_found", "run_id": run_id}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
