from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from db.migrate import upgrade_head
from obs.logging_setup import configure_logging
from services.deanonymize import deanonymize_file
from services.pipeline import resume_pipeline, run_detect_only, run_pipeline

app = typer.Typer(
    name="pii-pipeline",
    help="PII detect / anonymize / rewrite / encrypted vault map (Ollama + SQLite).",
    add_completion=False,
)
db_app = typer.Typer(help="Database migrations")
app.add_typer(db_app, name="db")


@app.callback()
def _root() -> None:
    configure_logging()


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations to head."""
    try:
        upgrade_head()
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("database upgraded to head")


@app.command("run")
def run_cmd(
    file: Path = typer.Argument(..., exists=False, help="Input .txt/.md/.pdf/.docx or -"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", help="Artifacts directory"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip escalate gate and continue anonymization",
    ),
) -> None:
    """Full pipeline: detect → verify → anonymize → rewrite → report → seal vault."""
    source: str | Path = "-" if str(file) == "-" else file
    try:
        result = run_pipeline(source, out_dir=out_dir, force=force)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"status={result.status}")
    if result.vault_id:
        typer.echo(f"vault_id={result.vault_id}")
    if result.out_dir:
        typer.echo(f"artifacts={result.out_dir}")
    if result.escalate or result.interrupted:
        typer.secho(
            "Escalated for human review. Resume with: pii-pipeline resume --run-id "
            f"{result.run_id}",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=2)
    if result.status == "failed" or result.status == "failed_residual_pii":
        raise typer.Exit(code=1)


@app.command("resume")
def resume_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Interrupted run id"),
    force: bool = typer.Option(True, "--force/--no-force", help="Approve and continue"),
) -> None:
    """Resume pipeline after escalate interrupt."""
    try:
        result = resume_pipeline(run_id, force=force)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"status={result.status}")
    if result.vault_id:
        typer.echo(f"vault_id={result.vault_id}")
    if result.out_dir:
        typer.echo(f"artifacts={result.out_dir}")
    if result.status in {"failed", "failed_residual_pii"}:
        raise typer.Exit(code=1)


@app.command("detect")
def detect_cmd(
    file: Path = typer.Argument(..., help="Input .txt/.md/.pdf/.docx or -"),
) -> None:
    """Detect + verify only (debug)."""
    source: str | Path = "-" if str(file) == "-" else file
    try:
        result = run_detect_only(source)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"status={result.status}")
    typer.echo(f"artifacts={result.out_dir}")
    counts = result.report.get("entity_counts") or {}
    typer.echo(f"entity_counts={counts}")


@app.command("deanonymize")
def deanonymize_cmd(
    redacted_file: Path = typer.Argument(..., exists=True, readable=True),
    vault_id: Optional[str] = typer.Option(None, "--vault-id"),
    run_id: Optional[str] = typer.Option(None, "--run-id"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
) -> None:
    """Restore plaintext using encrypted map from SQLite vault."""
    try:
        out = deanonymize_file(
            redacted_file,
            vault_id=vault_id,
            run_id=run_id,
            output_path=output,
        )
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote={out}")


if __name__ == "__main__":
    app()
