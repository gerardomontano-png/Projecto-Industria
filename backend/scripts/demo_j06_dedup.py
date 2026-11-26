"""
Demostración reproducible de la política de deduplicación (J06).

Simula una línea con una pieza quieta (muchos frames idénticos), que luego se
mueve, y una segunda pieza distinta. Compara cuántas detecciones se guardarían
sin la política y cuántas con ella. No necesita cámara, modelos ni red.

Ejecutar desde la carpeta backend:
    python scripts/demo_j06_dedup.py
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
from app.db.models import Camera, Detection, ProcessingRun, RunKind, SourceType  # noqa: E402
from app.services.dedup_policy import DedupConfig, DedupPolicy, describe_policy  # noqa: E402
from app.services.detection_schemas import DetectionEventInput, DetectionInput  # noqa: E402
from app.services.detection_store import DetectionStoreService  # noqa: E402

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def di(label, clase, box) -> DetectionInput:
    return DetectionInput(label=label, confidence=0.9, class_id=clase,
                          x1=box[0], y1=box[1], x2=box[2], y2=box[3])


def correr(db, politica) -> int:
    """Simula la línea y devuelve cuántas detecciones quedaron guardadas."""
    cam = Camera(name=f"L-{id(politica)}", source=str(id(politica) % 1000),
                 source_type=SourceType.USB)
    run = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="yolo", created_at=T0)
    run.start(at=T0)
    db.add(cam)
    db.flush()
    svc = DetectionStoreService(db, politica)

    seq = 0
    pieza_quieta = (100, 100, 200, 200)

    # 1) La pieza A permanece quieta 3 segundos a 30 fps (90 frames idénticos)
    for i in range(90):
        svc.save_event(DetectionEventInput(
            run_id=run.id, frame_seq=seq, captured_at=T0 + timedelta(seconds=i / 30.0),
            detections=[di("pieza", 1, pieza_quieta)]))
        seq += 1

    # 2) La pieza A se mueve a otra posición (nueva observación)
    svc.save_event(DetectionEventInput(
        run_id=run.id, frame_seq=seq, captured_at=T0 + timedelta(seconds=3.1),
        detections=[di("pieza", 1, (400, 100, 500, 200))]))
    seq += 1

    # 3) Aparece una pieza B distinta, al mismo tiempo que la A
    svc.save_event(DetectionEventInput(
        run_id=run.id, frame_seq=seq, captured_at=T0 + timedelta(seconds=3.2),
        detections=[di("pieza", 1, (400, 100, 500, 200)),      # A, misma posición
                    di("tornillo", 2, (50, 50, 90, 90))]))      # B, distinta

    return db.query(Detection).count()


def main() -> None:
    titulo("Escenario simulado")
    print("  1. Una pieza quieta frente a la cámara durante 3 s (90 frames a 30 fps).")
    print("  2. La misma pieza se mueve a otra posición.")
    print("  3. Aparece una segunda pieza, distinta, junto a la primera.")

    titulo("Sin política de deduplicación")
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        total_sin = correr(db, DedupPolicy(DedupConfig(enabled=False)))
    engine.dispose()
    print(f"  Detecciones guardadas: {total_sin}")
    print("  (90 de la pieza quieta + 1 al moverse + 2 del último frame = 93)")

    titulo("Con política (ventana 2 s, solape ≥ 50%)")
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        total_con = correr(db, DedupPolicy(DedupConfig(window_seconds=2.0, iou_threshold=0.5)))
    engine.dispose()
    print(f"  Detecciones guardadas: {total_con}")
    print("  La pieza quieta se reduce a muy pocas; la que se mueve y la pieza")
    print("  distinta se conservan.")

    titulo("Resultado")
    ahorro = (1 - total_con / total_sin) * 100
    print(f"  Se redujo de {total_sin} a {total_con} detecciones "
          f"({ahorro:.0f}% menos), sin perder las observaciones distintas.")

    titulo("Política aplicada")
    print("  " + describe_policy(DedupConfig(window_seconds=2.0, iou_threshold=0.5)))


if __name__ == "__main__":
    main()
