"""
Pruebas de configuración, sesiones, repositorios y migración — J02.

Cada prueba usa una base SQLite temporal en disco, nueva por caso (las
migraciones de Alembic necesitan una conexión real, no `:memory:`, porque cada
conexión en memoria vería una base distinta).

Criterios cubiertos:
  C1  Las migraciones crean la base desde un entorno limpio.
  C2  Las sesiones se abren, confirman, revierten y cierran correctamente.
  C3  Las pruebas de repositorio son reproducibles.

Ejecutar:
    cd backend
    python -m pytest tests/test_persistence.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import (
    Base,
    Camera,
    CameraStatus,
    Detection,
    DetectionEvent,
    ProcessingRun,
    RunKind,
    SourceType,
)
from app.db.config import DatabaseSettings, get_database_settings
from app.db.repositories import (
    CameraRepository,
    DetectionEventRepository,
    DetectionRepository,
    ProcessingRunRepository,
)
from app.db.session import (
    dispose_engine,
    get_session,
    get_session_factory,
    init_engine,
    session_scope,
)

BACKEND = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    """Una base SQLite temporal, propia de cada prueba, vía la variable de entorno."""
    url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DB_URL", url)
    get_database_settings.cache_clear()
    yield url
    get_database_settings.cache_clear()
    dispose_engine()


@pytest.fixture
def engine(db_url):
    """Motor sobre la base temporal, con las tablas ya creadas por el modelo."""
    engine = init_engine(force=True)
    Base.metadata.create_all(engine)
    yield engine
    dispose_engine()


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def camara(nombre="Línea 1", fuente="0", tipo=SourceType.USB) -> Camera:
    return Camera(name=nombre, source=fuente, source_type=tipo)


def corrida(cam: Camera, kind=RunKind.INFERENCE_STREAM) -> ProcessingRun:
    run = ProcessingRun(
        camera=cam,
        kind=kind,
        model_id=None if kind == RunKind.STREAM else "yolo26n",
        parameters={"conf": 0.25},
        created_at=T0,
    )
    run.start(at=T0 + timedelta(seconds=1))
    return run


# ── C1: migraciones desde un entorno limpio ──────────────────────────────────

def test_c1_la_migracion_crea_todo_el_esquema(db_url):
    command.upgrade(alembic_config(db_url), "head")

    engine = init_engine(force=True)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == {
        "alembic_version", "cameras", "processing_runs",
        "detection_events", "detections",
    }
    indices = {
        ix["name"] for tabla in Base.metadata.sorted_tables
        for ix in inspector.get_indexes(tabla.name)
    }
    assert "ix_detection_events_camera_id_captured_at" in indices
    assert "ix_detections_label" in indices


def test_c1_el_esquema_migrado_coincide_con_el_modelo(db_url):
    """Lo que crea la migración debe ser igual a lo que declara el modelo."""
    command.upgrade(alembic_config(db_url), "head")
    migrado = inspect(init_engine(force=True))

    tablas_modelo = {t.name for t in Base.metadata.sorted_tables}
    tablas_migradas = set(migrado.get_table_names()) - {"alembic_version"}
    assert tablas_migradas == tablas_modelo

    for tabla in Base.metadata.sorted_tables:
        columnas_modelo = {c.name for c in tabla.columns}
        columnas_migradas = {c["name"] for c in migrado.get_columns(tabla.name)}
        assert columnas_migradas == columnas_modelo, tabla.name


def test_c1_upgrade_y_downgrade_son_reversibles(db_url):
    config = alembic_config(db_url)

    command.upgrade(config, "head")
    con_datos = inspect(init_engine(force=True))
    assert "cameras" in con_datos.get_table_names()

    command.downgrade(config, "base")
    limpio = inspect(init_engine(force=True))
    assert set(limpio.get_table_names()) <= {"alembic_version"}


def test_c1_la_migracion_aplica_las_restricciones(db_url):
    """La base creada por la migración rechaza datos inválidos, igual que el modelo."""
    command.upgrade(alembic_config(db_url), "head")
    engine = init_engine(force=True)

    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            conn.execute(text(
                "INSERT INTO processing_runs (id, camera_id, kind, parameters, status, "
                "created_at, frames_processed) "
                "VALUES ('r1', 'camara-fantasma', 'stream', '{}', 'pending', "
                "'2026-11-01 12:00:00.000000', 0)"
            ))


# ── C2: sesiones ─────────────────────────────────────────────────────────────

def test_c2_session_scope_confirma_al_terminar_bien(engine):
    with session_scope() as db:
        db.add(camara())

    with session_scope() as db:
        assert CameraRepository(db).count() == 1


def test_c2_session_scope_revierte_ante_un_error(engine):
    class ErrorDePrueba(Exception):
        pass

    with pytest.raises(ErrorDePrueba):
        with session_scope() as db:
            db.add(camara("A", "0"))
            db.flush()
            raise ErrorDePrueba()

    with session_scope() as db:
        assert CameraRepository(db).count() == 0


def test_c2_rollback_deja_la_sesion_reutilizable(engine):
    # Prueba directa del rollback: una misma sesión, un error de integridad, y
    # después debe poder seguir trabajando. Sin el rollback de session_scope, la
    # sesión quedaría en estado fallido y el segundo add reventaría.
    factory = get_session_factory()
    db = factory()
    try:
        db.add(camara("Única", "0"))
        db.commit()

        db.add(camara("Choca", "0"))  # fuente repetida
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()  # es lo que hace session_scope ante el error

        db.add(camara("Nueva", "1"))  # la sesión sigue usable
        db.commit()
        assert CameraRepository(db).count() == 2
    finally:
        db.close()


def test_c2_una_violacion_de_integridad_revierte_toda_la_unidad(engine):
    with session_scope() as db:
        db.add(camara("Única", "0"))

    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(camara("Otra", "1"))        # válida
            db.add(camara("Única", "2"))       # nombre repetido: falla

    with session_scope() as db:
        # La cámara válida también se revirtió: la unidad de trabajo es atómica
        assert CameraRepository(db).count() == 1


def test_c2_la_dependencia_de_fastapi_confirma_al_agotar_el_generador(engine):
    # FastAPI agota el generador (next hasta StopIteration) cuando la petición
    # terminó bien; ese es el punto donde get_session confirma.
    generador = get_session()
    db = next(generador)
    db.add(camara())
    with pytest.raises(StopIteration):
        next(generador)  # cierra el bloque normalmente → commit

    with session_scope() as db:
        assert CameraRepository(db).count() == 1


def test_c2_la_dependencia_revierte_si_la_peticion_falla(engine):
    # Si la petición lanza, FastAPI inyecta la excepción con .throw(); get_session
    # revierte.
    generador = get_session()
    db = next(generador)
    db.add(camara())
    db.flush()
    with pytest.raises(ValueError):
        generador.throw(ValueError("la petición falló"))

    with session_scope() as db:
        assert CameraRepository(db).count() == 0


def test_c2_init_engine_es_idempotente_y_force_reinicia(db_url):
    primero = init_engine()
    assert init_engine() is primero          # misma instancia
    assert init_engine(force=True) is not primero


# ── C3: repositorios reproducibles ───────────────────────────────────────────

def test_c3_guardar_y_recuperar_la_cadena_completa(engine):
    with session_scope() as db:
        cam = camara()
        run = corrida(cam)
        ev = DetectionEvent(
            run=run, camera_id=cam.id, frame_seq=3,
            captured_at=T0 + timedelta(seconds=2),
            processed_at=T0 + timedelta(seconds=2, milliseconds=40),
        )
        ev.detections = [
            Detection(label="pieza", confidence=0.9, x1=10, y1=10, x2=100, y2=100),
        ]
        CameraRepository(db).add(cam)
        DetectionEventRepository(db).add(ev)
        cam_id, run_id = cam.id, run.id

    with session_scope() as db:
        cam = CameraRepository(db).get(cam_id)
        assert cam.name == "Línea 1"
        eventos = DetectionEventRepository(db).list_for_run(run_id)
        assert eventos[0].detections[0].label == "pieza"


def test_c3_repositorio_de_camaras_consultas(engine):
    with session_scope() as db:
        repo = CameraRepository(db)
        repo.add(camara("Activa 1", "0"))
        repo.add(camara("Activa 2", "1"))
        repo.add(Camera(name="Retirada", source="2", source_type=SourceType.USB,
                        status=CameraStatus.RETIRED))

    with session_scope() as db:
        repo = CameraRepository(db)
        activas = repo.list_active()
        assert [c.name for c in activas] == ["Activa 1", "Activa 2"]
        assert repo.get_by_name("Retirada").status == CameraStatus.RETIRED
        assert repo.get_by_source(SourceType.USB, "1").name == "Activa 2"
        assert repo.get_by_name("No existe") is None


def test_c3_historial_de_corridas_ordenado(engine):
    with session_scope() as db:
        cam = camara()
        CameraRepository(db).add(cam)
        for i in range(3):
            run = ProcessingRun(
                camera=cam, kind=RunKind.STREAM,
                created_at=T0 + timedelta(hours=i),
            )
            ProcessingRunRepository(db).add(run)
        cam_id = cam.id

    with session_scope() as db:
        historial = ProcessingRunRepository(db).history_for_camera(cam_id, limit=2)
        assert len(historial) == 2
        # Más reciente primero
        assert historial[0].created_at > historial[1].created_at


def test_c3_corridas_activas_excluyen_las_terminadas(engine):
    with session_scope() as db:
        cam = camara()
        CameraRepository(db).add(cam)
        en_curso = corrida(cam, RunKind.STREAM)
        terminada = corrida(camara("B", "1"), RunKind.STREAM)
        terminada.complete(at=T0 + timedelta(seconds=5))
        ProcessingRunRepository(db).add_all([en_curso, terminada])

    with session_scope() as db:
        activas = ProcessingRunRepository(db).list_active()
        assert len(activas) == 1


def test_c3_conteo_de_detecciones_por_etiqueta(engine):
    with session_scope() as db:
        cam = camara()
        run = corrida(cam)
        ev = DetectionEvent(
            run=run, camera_id=cam.id, frame_seq=1,
            captured_at=T0 + timedelta(seconds=2),
            processed_at=T0 + timedelta(seconds=2, milliseconds=10),
        )
        ev.detections = [
            Detection(label="pieza", confidence=0.9, x1=0, y1=0, x2=10, y2=10),
            Detection(label="pieza", confidence=0.8, x1=20, y1=20, x2=30, y2=30),
            Detection(label="tornillo", confidence=0.7, x1=40, y1=40, x2=50, y2=50),
        ]
        CameraRepository(db).add(cam)
        DetectionEventRepository(db).add(ev)
        run_id = run.id

    with session_scope() as db:
        conteo = DetectionRepository(db).count_by_label_for_run(run_id)
        assert conteo == {"pieza": 2, "tornillo": 1}


def test_c3_eventos_de_una_camara_por_rango_de_fechas(engine):
    with session_scope() as db:
        cam = camara()
        run = corrida(cam)
        CameraRepository(db).add(cam)
        for minuto in (0, 30, 90):  # dos dentro de la hora, uno fuera
            DetectionEventRepository(db).add(DetectionEvent(
                run=run, camera_id=cam.id, frame_seq=minuto,
                captured_at=T0 + timedelta(minutes=minuto),
                processed_at=T0 + timedelta(minutes=minuto, seconds=1),
            ))
        cam_id = cam.id

    with session_scope() as db:
        eventos = DetectionEventRepository(db).list_for_camera_between(
            cam_id, T0, T0 + timedelta(hours=1)
        )
        assert [e.frame_seq for e in eventos] == [0, 30]


# ── Configuración ─────────────────────────────────────────────────────────────

def test_config_lee_el_entorno(monkeypatch):
    monkeypatch.setenv("DB_URL", "sqlite+pysqlite:///./otra.db")
    monkeypatch.setenv("DB_ECHO", "true")
    get_database_settings.cache_clear()

    settings = get_database_settings()
    assert settings.url.endswith("otra.db")
    assert settings.echo is True
    assert settings.is_sqlite

    get_database_settings.cache_clear()


def test_config_enmascara_la_contrasena_de_la_url():
    settings = DatabaseSettings(url="postgresql+psycopg://user:s3cret@db:5432/vision")
    assert "s3cret" not in settings.safe_url
    assert "db:5432" in settings.safe_url


def test_config_parametros_de_pool_solo_fuera_de_sqlite():
    sqlite = DatabaseSettings(url="sqlite+pysqlite:///./x.db")
    assert "pool_size" not in sqlite.engine_kwargs()
    assert sqlite.engine_kwargs()["connect_args"] == {"check_same_thread": False}

    postgres = DatabaseSettings(url="postgresql+psycopg://u:p@h/db", pool_size=7)
    assert postgres.engine_kwargs()["pool_size"] == 7
    assert postgres.engine_kwargs()["pool_pre_ping"] is True
