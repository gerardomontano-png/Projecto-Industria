"""
Demostración reproducible de la capa de persistencia de J02.

Crea una base SQLite temporal, aplica la migración inicial, guarda datos con los
repositorios, consulta el historial, muestra que un error revierte toda la
unidad de trabajo y deshace la migración. Borra su base temporal al terminar.

No necesita cámara, modelos ni red.

Ejecutar desde la carpeta backend:
    python scripts/demo_j02_persistencia.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def main() -> None:
    carpeta = tempfile.mkdtemp(prefix="j02_demo_")
    ruta = Path(carpeta) / "demo.db"
    os.environ["DB_URL"] = f"sqlite+pysqlite:///{ruta}"

    # Importar después de fijar DB_URL, para que la configuración lo lea
    from alembic import command
    from alembic.config import Config

    from app.db import (
        Camera, Detection, DetectionEvent, ProcessingRun, RunKind, SourceType,
    )
    from app.db.config import get_database_settings
    from app.db.repositories import (
        CameraRepository, DetectionRepository, ProcessingRunRepository,
    )
    from app.db.session import dispose_engine, session_scope

    get_database_settings.cache_clear()
    backend = Path(__file__).resolve().parents[1]

    try:
        titulo("1. Configuración leída del entorno")
        settings = get_database_settings()
        print(f"  URL (segura): {settings.safe_url}")
        print(f"  ¿SQLite?:     {settings.is_sqlite}")

        titulo("2. Migración inicial sobre una base vacía")
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "head")
        print("  Esquema creado. Versión actual:")
        command.current(config)

        titulo("3. Guardar datos con los repositorios")
        with session_scope() as db:
            cam = Camera(
                name="Línea 1", source_type=SourceType.RTSP,
                source="rtsp://10.0.0.5:554/stream", credential_ref="CAMARA_LINEA1_RTSP",
            )
            run = ProcessingRun(
                camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="yolo26n",
                parameters={"conf": 0.25}, created_at=T0,
            )
            run.start(at=T0 + timedelta(seconds=1))
            ev = DetectionEvent(
                run=run, camera_id=cam.id, frame_seq=3,
                captured_at=T0 + timedelta(seconds=2),
                processed_at=T0 + timedelta(seconds=2, milliseconds=40),
            )
            ev.detections = [
                Detection(label="pieza", confidence=0.91, x1=40, y1=60, x2=200, y2=260),
                Detection(label="pieza", confidence=0.88, x1=300, y1=60, x2=460, y2=260),
                Detection(label="tornillo", confidence=0.72, x1=120, y1=300, x2=180, y2=360),
            ]
            run.frames_processed = 1
            run.complete(at=T0 + timedelta(seconds=3))
            CameraRepository(db).add(cam)
            db.add(ev)
            cam_id, run_id = cam.id, run.id
        print("  Cámara, corrida, evento y 3 detecciones guardados (una sola unidad de trabajo).")

        titulo("4. Consultas con los repositorios")
        with session_scope() as db:
            activas = CameraRepository(db).list_active()
            print(f"  Cámaras activas: {[c.name for c in activas]}")
            historial = ProcessingRunRepository(db).history_for_camera(cam_id)
            print(f"  Corridas de la cámara: {len(historial)} "
                  f"(última: {historial[0].status.value})")
            conteo = DetectionRepository(db).count_by_label_for_run(run_id)
            print(f"  Detecciones por etiqueta: {conteo}")

        titulo("5. Un error revierte toda la unidad de trabajo")
        try:
            with session_scope() as db:
                CameraRepository(db).add(Camera(
                    name="Temporal", source="9", source_type=SourceType.USB))
                print("  Dentro del bloque: se agregó 'Temporal'...")
                raise RuntimeError("algo falló a mitad del guardado")
        except RuntimeError as exc:
            print(f"  Error: {exc}")
        with session_scope() as db:
            total = CameraRepository(db).count()
        print(f"  Cámaras tras el error: {total} (la temporal NO se guardó ✓)")

        titulo("6. Deshacer la migración")
        command.downgrade(config, "base")
        print("  Esquema eliminado. La base queda vacía.")

    finally:
        dispose_engine()
        try:
            ruta.unlink(missing_ok=True)
            Path(carpeta).rmdir()
        except OSError:
            pass
        print(f"\n  Base temporal eliminada: {ruta}")


if __name__ == "__main__":
    main()
