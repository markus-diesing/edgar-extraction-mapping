"""
alembic/env.py — Alembic runtime environment.

The database URL is derived from config.DB_PATH so it always stays in sync
with the application's own setting — no copy-pasted connection strings.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Make the backend package importable when alembic is run from backend/
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve().parent.parent   # backend/
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import config as app_config          # noqa: E402  (after sys.path fix)
import database                       # noqa: E402  (registers all ORM models)

# ---------------------------------------------------------------------------
# Alembic Config object (from alembic.ini)
# ---------------------------------------------------------------------------
alembic_cfg = context.config

# Wire in the DB URL from our application config — single source of truth.
alembic_cfg.set_main_option(
    "sqlalchemy.url",
    f"sqlite:///{app_config.DB_PATH}",
)

# Interpret the config file for Python logging.
if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Expose the ORM metadata so --autogenerate can diff the models.
target_metadata = database.Base.metadata


# ---------------------------------------------------------------------------
# Offline mode (generate SQL without connecting)
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Emit migration SQL to stdout (no live DB connection required)."""
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite-specific: batch mode allows column/index alterations
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode (run against a live connection)
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    """Apply migrations to the live database."""
    connectable = engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite-specific: batch mode rewrites tables so ALTER TABLE works
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
