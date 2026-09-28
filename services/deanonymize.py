from __future__ import annotations

from pathlib import Path

from crypto.vault import decrypt_alias_map
from db.migrate import ensure_migrated
from db.repositories import VaultMapsRepo
from db.session import get_session_factory
from pii.anonymize import deanonymize_text


def deanonymize_file(
    redacted_path: str | Path,
    *,
    vault_id: str | None = None,
    run_id: str | None = None,
    output_path: str | Path | None = None,
) -> Path:
    if not vault_id and not run_id:
        raise ValueError("Provide --vault-id or --run-id")

    ensure_migrated()
    session = get_session_factory()()
    try:
        repo = VaultMapsRepo(session)
        row = repo.get_by_id(vault_id) if vault_id else repo.get_by_run_id(str(run_id))
        if row is None:
            raise ValueError("Vault map not found")
        alias_map = decrypt_alias_map(row.salt, row.nonce, row.ciphertext)
    finally:
        session.close()

    path = Path(redacted_path)
    text = path.read_text(encoding="utf-8")
    restored = deanonymize_text(text, alias_map)

    out = Path(output_path) if output_path else path.with_suffix(path.suffix + ".restored.txt")
    if output_path is None and path.name == "rewritten.txt":
        out = path.with_name("restored.txt")
    out.write_text(restored, encoding="utf-8")
    return out
