"""
Motor y sesiones de base de datos (J02).

Una aplicación tiene un solo motor (el pool de conexiones) y abre una sesión
por cada unidad de trabajo. Aquí se definen:

  - `init_engine` / `get_engine`: crean y comparten el motor del proceso.
  - `session_scope`: un contexto que abre una sesión, confirma si todo salió
    bien, revierte si hubo un error y siempre la cierra. Es la forma
    recomendada de trabajar con la base.
  - `get_session`: dependencia para FastAPI, con el mismo comportamiento.

La regla de oro: quien abre la sesión decide cuándo se confirma. Los
repositorios (ver app/db/repositories) nunca hacen commit; solo preparan los
cambios. Así, varias operaciones distintas pueden confirmarse juntas o
revertirse juntas.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import create_db_engine
from app.db.config import DatabaseSettings, get_database_settings

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def init_engine(settings: Optional[DatabaseSettings] = None, *, force: bool = False) -> Engine:
    """
    Crea el motor del proceso y la fábrica de sesiones.

    Es idempotente: si el motor ya existe, lo devuelve, salvo que `force` sea
    True (útil en pruebas para cambiar de base entre casos).
    """
    global _engine, _session_factory

    if _engine is not None and not force:
        return _engine

    if _engine is not None and force:
        _engine.dispose()

    settings = settings or get_database_settings()
    _engine = create_db_engine(settings.url, **settings.engine_kwargs())
    _session_factory = sessionmaker(
        bind=_engine, autoflush=False, expire_on_commit=False, future=True
    )
    return _engine


def get_engine() -> Engine:
    """Devuelve el motor del proceso, creándolo la primera vez."""
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Unidad de trabajo transaccional.

    Abre una sesión, la entrega, y al salir:
      - confirma (commit) si el bloque terminó sin excepción;
      - revierte (rollback) si hubo una excepción, y la vuelve a lanzar;
      - cierra la sesión en todos los casos.

    Uso:
        with session_scope() as db:
            repo = CameraRepository(db)
            repo.add(camara)
        # aquí ya se hizo commit
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """
    Dependencia de FastAPI (para usar con Depends).

    Entrega una sesión y la cierra al final. Confirma si la petición terminó
    bien y revierte si lanzó una excepción, igual que `session_scope`.
    """
    with session_scope() as session:
        yield session


def dispose_engine() -> None:
    """Cierra el motor y olvida la fábrica. Para el apagado del servicio y las pruebas."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
