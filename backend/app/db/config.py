"""
Configuración de la base de datos (J02).

La URL de conexión y los parámetros del pool se leen del entorno, con valores
por defecto pensados para desarrollo local (SQLite en un archivo). En
producción se define `DATABASE_URL` apuntando a PostgreSQL, sin tocar código.

La URL puede contener la contraseña del usuario de la base; por eso
`safe_url` ofrece una versión enmascarada para logs y diagnósticos.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class DatabaseSettings(BaseSettings):
    """Parámetros de conexión, tomados del entorno o del archivo .env."""

    url: str = Field(
        default="sqlite+pysqlite:///./data/vision.db",
        description="URL de conexión SQLAlchemy. En producción, PostgreSQL.",
    )
    echo: bool = Field(default=False, description="Registrar en consola el SQL ejecutado.")
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout: int = Field(default=30, ge=1)
    pool_recycle: int = Field(default=1800, ge=-1)

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_sqlite(self) -> bool:
        return make_url(self.url).get_backend_name() == "sqlite"

    @property
    def safe_url(self) -> str:
        """La URL con la contraseña enmascarada, apta para logs."""
        return make_url(self.url).render_as_string(hide_password=True)

    def engine_kwargs(self) -> dict:
        """
        Argumentos para create_engine según el motor.

        SQLite no usa un pool de conexiones como PostgreSQL, así que esos
        parámetros solo se aplican fuera de SQLite. Para SQLite en memoria o en
        archivo, se permite compartir la conexión entre hilos (el servidor lee
        la cámara en hilos aparte).
        """
        kwargs: dict = {"echo": self.echo, "future": True}
        if self.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
                pool_pre_ping=True,
            )
        return kwargs


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Instancia única de la configuración (se lee del entorno una sola vez)."""
    return DatabaseSettings()
