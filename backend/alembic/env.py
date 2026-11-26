"""
Entorno de migraciones de Alembic (J02).

La URL de la base y el esquema objetivo se toman de la aplicación, no del
alembic.ini, para tener una sola fuente de verdad y no escribir credenciales
en un archivo versionado.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.db.base import Base
from app.db.config import get_database_settings
from app.db.session import get_engine, init_engine

# Importar los modelos registra las tablas en Base.metadata
import app.db.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (modo --sql)."""
    settings = get_database_settings()
    context.configure(
        url=settings.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.is_sqlite,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica las migraciones conectándose a la base."""
    init_engine(force=True)
    settings = get_database_settings()
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # batch: SQLite no soporta ALTER TABLE completo; esto lo habilita
            render_as_batch=settings.is_sqlite,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
