from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from db.models import AuditLog, Run, VaultMap


class RunsRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, source_path: str, model_id: str | None) -> Run:
        run = Run(
            id=str(uuid4()),
            source_path=source_path,
            status="started",
            escalate=False,
            model_id=model_id,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def list_runs(self, *, limit: int = 50) -> list[Run]:
        return (
            self.session.query(Run)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .all()
        )

    def get(self, run_id: str) -> Run | None:
        return self.session.get(Run, run_id)

    def update_status(
        self,
        run_id: str,
        *,
        status: str,
        escalate: bool | None = None,
    ) -> None:
        run = self.get(run_id)
        if run is None:
            return
        run.status = status
        if escalate is not None:
            run.escalate = escalate
        if status in {"completed", "escalated", "failed"}:
            run.finished_at = datetime.now(UTC)
        self.session.commit()


class VaultMapsRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        *,
        run_id: str,
        salt: str,
        nonce: str,
        ciphertext: str,
    ) -> VaultMap:
        existing = self.session.query(VaultMap).filter_by(run_id=run_id).one_or_none()
        if existing:
            existing.salt = salt
            existing.nonce = nonce
            existing.ciphertext = ciphertext
            self.session.commit()
            self.session.refresh(existing)
            return existing
        row = VaultMap(
            id=str(uuid4()),
            run_id=run_id,
            salt=salt,
            nonce=nonce,
            ciphertext=ciphertext,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def get_by_id(self, vault_id: str) -> VaultMap | None:
        return self.session.get(VaultMap, vault_id)

    def get_by_run_id(self, run_id: str) -> VaultMap | None:
        return self.session.query(VaultMap).filter_by(run_id=run_id).one_or_none()


class AuditLogsRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        run_id: str,
        node_name: str,
        duration_ms: int,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        row = AuditLog(
            id=str(uuid4()),
            run_id=run_id,
            node_name=node_name,
            duration_ms=duration_ms,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list_for_run(self, run_id: str, *, limit: int = 200) -> list[AuditLog]:
        return (
            self.session.query(AuditLog)
            .filter_by(run_id=run_id)
            .order_by(AuditLog.created_at.asc())
            .limit(limit)
            .all()
        )
