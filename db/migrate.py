from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from alembic import command
from alembic.config import Config
from config.settings import get_settings
from db.session import get_engine


class DatabaseNotMigratedError(RuntimeError):
    pass


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    root = _project_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def required_tables_present() -> bool:
    engine = get_engine()
    names = set(inspect(engine).get_table_names())
    return {"runs", "vault_maps", "audit_logs"}.issubset(names)


def _alembic_version_present() -> bool:
    engine = get_engine()
    names = set(inspect(engine).get_table_names())
    return "alembic_version" in names


def upgrade_head() -> None:
    """Apply migrations. If legacy create_all DB exists without version, stamp head."""
    cfg = alembic_config()
    if required_tables_present():
        if not _alembic_version_present():
            command.stamp(cfg, "head")
            return
        command.upgrade(cfg, "head")
        return
    command.upgrade(cfg, "head")


def ensure_migrated() -> None:
    """Fail closed if schema missing — do not auto-create tables."""
    if required_tables_present():
        if not _alembic_version_present():
            # Align legacy DBs created via create_all
            command.stamp(alembic_config(), "head")
        return
    raise DatabaseNotMigratedError(
        "Database schema missing. Run: pii-pipeline db upgrade"
    )
