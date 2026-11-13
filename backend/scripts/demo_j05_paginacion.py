"""
Demostración reproducible de paginación, ordenamiento y límites (J05).

Sobre una base en memoria con muchos eventos, recorre el historial por offset y
por cursor, ordena por distintos campos, demuestra la estabilidad del cursor
ante inserciones y muestra cómo se rechazan las consultas inválidas.

Ejecutar desde la carpeta backend:
    python scripts/demo_j05_paginacion.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base, create_db_engine  # noqa: E402
from app.db.models import Camera, ProcessingRun, RunKind, SourceType  # noqa: E402
from app.services.detection_schemas import (  # noqa: E402
    DetectionEventInput, DetectionInput, DetectionValidationError, EventQuery,
)
from app.services.detection_store import DetectionStoreService  # noqa: E402
from app.services.query_pagination import (  # noqa: E402
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginationError,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def det() -> DetectionInput:
    return DetectionInput(label="pieza", confidence=0.9, class_id=1, x1=0, y1=0, x2=10, y2=10)


def main() -> None:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        cam = Camera(name="Línea 1", source="0", source_type=SourceType.USB)
        run = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="yolo", created_at=T0)
        run.start(at=T0)
        db.add(cam)
        db.flush()
        svc = DetectionStoreService(db)

        for i in range(25):
            svc.save_event(DetectionEventInput(
                run_id=run.id, frame_seq=i, captured_at=T0 + timedelta(hours=i),
                detections=[det()]))

        titulo("1. Límites máximos")
        print(f"  Tamaño de página por defecto: {DEFAULT_PAGE_SIZE}")
        print(f"  Tope máximo: {MAX_PAGE_SIZE}")
        sin_limit = svc.query(EventQuery())
        print(f"  Hay 25 eventos; sin pedir limit, una página trae {len(sin_limit.events)} "
              f"(total informado: {sin_limit.total}).")

        titulo("2. Paginación por offset")
        offset, paginas, vistos = 0, 0, []
        while True:
            page = svc.query(EventQuery(limit=10, offset=offset))
            paginas += 1
            vistos.extend(e.id for e in page.events)
            print(f"  Página {paginas}: {len(page.events)} eventos, ¿hay más? {page.has_more}")
            if not page.has_more:
                break
            offset += 10
        print(f"  Total recorrido: {len(vistos)} eventos, sin repetidos: {len(set(vistos)) == 25}")

        titulo("3. Ordenamiento configurable")
        asc = svc.query(EventQuery(limit=5, sort_by="frame_seq", sort_dir="asc"))
        print(f"  Por frame_seq ascendente: {[e.frame_seq for e in asc.events]}")
        desc = svc.query(EventQuery(limit=5, sort_by="frame_seq", sort_dir="desc"))
        print(f"  Por frame_seq descendente: {[e.frame_seq for e in desc.events]}")

        titulo("4. Cursor estable ante inserciones")
        primera = svc.query(EventQuery(limit=10))
        print(f"  Primera página por cursor: {len(primera.events)} eventos.")
        svc.save_event(DetectionEventInput(
            run_id=run.id, frame_seq=999, captured_at=T0 + timedelta(hours=100),
            detections=[det()]))
        print("  Se insertó un evento nuevo y más reciente...")
        segunda = svc.query(EventQuery(limit=10, cursor=primera.next_cursor))
        repetidos = {e.id for e in primera.events} & {e.id for e in segunda.events}
        print(f"  Segunda página por cursor: {len(segunda.events)} eventos. "
              f"¿Reaparece alguno de la primera? {'Sí ✗' if repetidos else 'No ✓'}")

        titulo("5. Consultas inválidas")
        for descripcion, consulta in [
            ("limit enorme (1 000 000)", EventQuery(limit=1_000_000)),
            ("ordenar por campo prohibido", EventQuery(sort_by="credential_ref")),
            ("dirección inválida", EventQuery(sort_by="captured_at", sort_dir="arriba")),
            ("cursor corrupto", EventQuery(cursor="esto-no-es-un-cursor")),
        ]:
            try:
                svc.query(consulta)
                print(f"  ✗ {descripcion}: ¡se aceptó!")
            except (PaginationError, DetectionValidationError) as exc:
                print(f"  ✓ {descripcion} [{exc.field}]: {exc}")

    engine.dispose()


if __name__ == "__main__":
    main()
