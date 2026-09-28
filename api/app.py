from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from db.migrate import ensure_migrated
from db.repositories import AuditLogsRepo, RunsRepo, VaultMapsRepo
from db.session import get_session_factory
from obs.logging_setup import configure_logging
from services.deanonymize import deanonymize_file
from services.pipeline import resume_pipeline, run_pipeline

configure_logging()
app = FastAPI(title="PII Pipeline API", version="1.0.0")
_executor = ThreadPoolExecutor(max_workers=2)


class RunRequest(BaseModel):
    path: str = Field(..., description="Absolute or relative path to input file")
    force: bool = False
    out_dir: str | None = None


class DeanonymizeRequest(BaseModel):
    redacted_path: str
    vault_id: str | None = None
    run_id: str | None = None
    output_path: str | None = None


class ResumeRequest(BaseModel):
    force: bool = True


def _run_sync(fn, *args, **kwargs):
    return _executor.submit(fn, *args, **kwargs).result()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/runs")
def create_run(body: RunRequest) -> dict[str, Any]:
    try:
        ensure_migrated()
        result = _run_sync(
            run_pipeline,
            body.path,
            out_dir=body.out_dir,
            force=body.force,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "run_id": result.run_id,
        "status": result.status,
        "escalate": result.escalate,
        "interrupted": result.interrupted,
        "vault_id": result.vault_id,
        "out_dir": result.out_dir,
        "errors": result.errors,
        "report": result.report,
    }


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        ensure_migrated()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    session = get_session_factory()()
    try:
        run = RunsRepo(session).get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        vault = VaultMapsRepo(session).get_by_run_id(run_id)
        return {
            "id": run.id,
            "source_path": run.source_path,
            "status": run.status,
            "escalate": run.escalate,
            "model_id": run.model_id,
            "vault_id": vault.id if vault else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
    finally:
        session.close()


@app.get("/v1/runs/{run_id}/audit")
def get_audit(run_id: str) -> dict[str, Any]:
    ensure_migrated()
    session = get_session_factory()()
    try:
        rows = AuditLogsRepo(session).list_for_run(run_id)
        return {
            "run_id": run_id,
            "events": [
                {
                    "node_name": r.node_name,
                    "duration_ms": r.duration_ms,
                    "payload": json.loads(r.payload_json or "{}"),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    finally:
        session.close()


@app.post("/v1/runs/{run_id}/resume")
def resume_run(run_id: str, body: ResumeRequest) -> dict[str, Any]:
    try:
        result = _run_sync(resume_pipeline, run_id, force=body.force)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "run_id": result.run_id,
        "status": result.status,
        "vault_id": result.vault_id,
        "out_dir": result.out_dir,
        "errors": result.errors,
    }


@app.post("/v1/deanonymize")
def deanonymize(body: DeanonymizeRequest) -> dict[str, Any]:
    try:
        out = _run_sync(
            deanonymize_file,
            body.redacted_path,
            vault_id=body.vault_id,
            run_id=body.run_id,
            output_path=body.output_path,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"wrote": str(out)}


def main() -> None:
    import uvicorn

    uvicorn.run("api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
