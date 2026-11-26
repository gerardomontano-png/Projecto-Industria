"""
Pruebas de la política de deduplicación de detecciones — J06.

Las primeras prueban la política de forma aislada (una decisión pura); las
siguientes la prueban a través del guardado real, con una base en memoria.

Criterios cubiertos:
  C1  La política reduce duplicados sin eliminar eventos distintos.
  C2  La ventana y el criterio de equivalencia están documentados (y se validan).
  C3  Las pruebas cubren detecciones repetidas, distintas y casos límite.

Ejecutar:
    cd backend
    python -m pytest tests/test_dedup.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, create_db_engine
from app.db.models import Camera, Detection, ProcessingRun, RunKind, SourceType
from app.services.dedup_policy import (
    DedupConfig,
    DedupConfigError,
    DedupPolicy,
    DetectionKey,
    describe_policy,
    iou,
    _Box,
)
from app.services.detection_schemas import DetectionEventInput, DetectionInput
from app.services.detection_store import DetectionStoreService

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def key(camera="cam", clase=1, label="pieza", box=(0, 0, 10, 10)) -> DetectionKey:
    return DetectionKey(camera_id=camera, class_id=clase, label=label, box=box)


# ── IoU y equivalencia ───────────────────────────────────────────────────────

def test_iou_de_cajas_identicas_es_uno():
    b = _Box(0, 0, 10, 10)
    assert iou(b, b) == 1.0


def test_iou_de_cajas_disjuntas_es_cero():
    assert iou(_Box(0, 0, 10, 10), _Box(100, 100, 110, 110)) == 0.0


def test_iou_de_cajas_parcialmente_solapadas():
    # Dos cajas 10x10 que comparten la mitad: intersección 50, unión 150 → 1/3
    assert iou(_Box(0, 0, 10, 10), _Box(5, 0, 15, 10)) == pytest.approx(1 / 3)


def test_equivalencia_exige_misma_camara():
    p = DedupPolicy()
    assert not p.equivalent(key(camera="a"), key(camera="b"))


def test_equivalencia_por_defecto_exige_clase_y_etiqueta():
    p = DedupPolicy()
    assert not p.equivalent(key(clase=1), key(clase=2))
    assert not p.equivalent(key(label="pieza"), key(label="tornillo"))


def test_equivalencia_puede_ignorar_clase_y_etiqueta():
    p = DedupPolicy(DedupConfig(match_class=False, match_label=False))
    # Solo cuenta cámara + posición
    assert p.equivalent(key(clase=1, label="pieza"), key(clase=2, label="tornillo"))


def test_cajas_poco_solapadas_no_son_equivalentes():
    p = DedupPolicy(DedupConfig(iou_threshold=0.5))
    # IoU 1/3 < 0.5 → no son la misma posición
    assert not p.equivalent(key(box=(0, 0, 10, 10)), key(box=(5, 0, 15, 10)))


# ── Ventana temporal ─────────────────────────────────────────────────────────

def test_c1_duplicado_dentro_de_la_ventana_se_detecta():
    p = DedupPolicy(DedupConfig(window_seconds=2.0))
    assert p.is_duplicate(key(), 100.0) is False   # primera vez: se registra
    assert p.is_duplicate(key(), 101.0) is True    # 1s después: duplicado


def test_c1_fuera_de_la_ventana_vuelve_a_registrarse():
    p = DedupPolicy(DedupConfig(window_seconds=2.0))
    assert p.is_duplicate(key(), 100.0) is False
    assert p.is_duplicate(key(), 103.0) is False   # 3s después: ya no es duplicado


def test_c1_la_ventana_se_desliza_con_cada_duplicado():
    """
    Una pieza quieta que aparece cada segundo debe deduplicarse siempre, no solo
    durante los primeros 2 segundos: cada duplicado refresca la ventana.
    """
    p = DedupPolicy(DedupConfig(window_seconds=2.0))
    assert p.is_duplicate(key(), 100.0) is False
    for t in (101.0, 102.0, 103.0, 104.0):
        assert p.is_duplicate(key(), t) is True


def test_c1_detecciones_distintas_nunca_se_deduplican():
    p = DedupPolicy()
    assert p.is_duplicate(key(clase=1), 100.0) is False
    assert p.is_duplicate(key(clase=2), 100.0) is False   # otra clase, mismo instante
    assert p.is_duplicate(key(box=(50, 50, 60, 60)), 100.0) is False  # otra posición


def test_c1_cada_camara_lleva_su_propia_cuenta():
    p = DedupPolicy()
    assert p.is_duplicate(key(camera="a"), 100.0) is False
    assert p.is_duplicate(key(camera="b"), 100.0) is False  # otra cámara: no es duplicado
    assert p.is_duplicate(key(camera="a"), 100.5) is True   # la misma de A sí


def test_politica_desactivada_no_deduplica_nada():
    p = DedupPolicy(DedupConfig(enabled=False))
    assert p.is_duplicate(key(), 100.0) is False
    assert p.is_duplicate(key(), 100.0) is False


# ── C2: validación y descripción de la política ──────────────────────────────

@pytest.mark.parametrize(
    "cambios, campo",
    [
        ({"window_seconds": 0}, "window_seconds"),
        ({"window_seconds": -1}, "window_seconds"),
        ({"iou_threshold": 0}, "iou_threshold"),
        ({"iou_threshold": 1.5}, "iou_threshold"),
    ],
)
def test_c2_configuracion_invalida_se_rechaza(cambios, campo):
    with pytest.raises(DedupConfigError) as info:
        DedupPolicy(DedupConfig(**cambios))
    assert info.value.field == campo


def test_c2_la_politica_se_describe_en_texto():
    texto = describe_policy(DedupConfig(window_seconds=2, iou_threshold=0.5))
    assert "2 s" in texto and "50%" in texto and "cámara" in texto

    apagada = describe_policy(DedupConfig(enabled=False))
    assert "desactivada" in apagada.lower()


# ── Casos límite ─────────────────────────────────────────────────────────────

def test_limite_iou_justo_en_el_umbral_es_duplicado():
    # IoU exactamente igual al umbral debe contar como duplicado (>=)
    p = DedupPolicy(DedupConfig(iou_threshold=1 / 3))
    assert p.equivalent(key(box=(0, 0, 10, 10)), key(box=(5, 0, 15, 10)))


def test_limite_tiempo_justo_en_el_borde_de_la_ventana():
    # A exactamente window_seconds de distancia YA está fuera (< estricto)
    p = DedupPolicy(DedupConfig(window_seconds=2.0))
    assert p.is_duplicate(key(), 100.0) is False
    assert p.is_duplicate(key(), 102.0) is False  # justo 2s: fuera


def test_reset_olvida_lo_visto():
    p = DedupPolicy()
    p.is_duplicate(key(), 100.0)
    p.reset()
    assert p.is_duplicate(key(), 100.5) is False  # como si fuera la primera vez


# ── A través del guardado real ───────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def run(db):
    cam = Camera(name="Línea 1", source="0", source_type=SourceType.USB)
    r = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="yolo", created_at=T0)
    r.start(at=T0)
    db.add(cam)
    db.flush()
    return r


def di(label="pieza", clase=1, box=(0, 0, 10, 10), conf=0.9) -> DetectionInput:
    return DetectionInput(label=label, confidence=conf, class_id=clase,
                          x1=box[0], y1=box[1], x2=box[2], y2=box[3])


def ev(run, seq, segundos, dets) -> DetectionEventInput:
    return DetectionEventInput(
        run_id=run.id, frame_seq=seq,
        captured_at=T0 + timedelta(seconds=segundos), detections=dets,
    )


def test_c1_guardado_omite_la_deteccion_repetida_pero_guarda_el_evento(db, run):
    svc = DetectionStoreService(db, DedupPolicy(DedupConfig(window_seconds=2.0)))

    r1 = svc.save_event(ev(run, 1, 0, [di()]))
    r2 = svc.save_event(ev(run, 2, 0.5, [di()]))   # misma pieza, 0.5s después

    assert len(r1.detections) == 1
    assert len(r2.detections) == 0                 # la detección se omitió...
    assert r2.frame_seq == 2                        # ...pero el evento se guardó
    # En la base hay dos eventos y una sola detección
    assert db.query(Detection).count() == 1


def test_c1_una_pieza_quieta_se_guarda_una_vez_no_cien(db, run):
    svc = DetectionStoreService(db, DedupPolicy(DedupConfig(window_seconds=2.0)))

    # 100 frames a 30 fps (~3.3s) con la misma pieza inmóvil
    for i in range(100):
        svc.save_event(ev(run, i, i / 30.0, [di()]))

    # Sin dedup serían 100 detecciones; con la ventana de 2s, solo las de los
    # bordes de cada ventana. Debe ser muy pocas, no 100.
    guardadas = db.query(Detection).count()
    assert guardadas < 5
    assert guardadas >= 1                           # pero al menos una


def test_c1_dos_piezas_distintas_en_el_mismo_frame_se_guardan_ambas(db, run):
    svc = DetectionStoreService(db)
    r = svc.save_event(ev(run, 1, 0, [
        di("pieza", 1, (0, 0, 10, 10)),
        di("tornillo", 2, (50, 50, 60, 60)),
    ]))
    assert len(r.detections) == 2


def test_c1_la_misma_caja_con_distinta_clase_no_se_deduplica(db, run):
    svc = DetectionStoreService(db)
    r = svc.save_event(ev(run, 1, 0, [
        di("pieza", 1, (0, 0, 10, 10)),
        di("tornillo", 2, (0, 0, 10, 10)),   # misma posición, otra clase
    ]))
    assert len(r.detections) == 2


def test_c1_una_pieza_que_se_mueve_se_guarda_en_cada_posicion(db, run):
    svc = DetectionStoreService(db, DedupPolicy(DedupConfig(window_seconds=5.0)))

    # La misma pieza en posiciones que no se solapan: son observaciones distintas
    svc.save_event(ev(run, 1, 0, [di(box=(0, 0, 10, 10))]))
    svc.save_event(ev(run, 2, 0.5, [di(box=(100, 0, 110, 10))]))
    svc.save_event(ev(run, 3, 1.0, [di(box=(200, 0, 210, 10))]))

    assert db.query(Detection).count() == 3


def test_c1_fuera_de_la_ventana_la_pieza_se_registra_de_nuevo(db, run):
    svc = DetectionStoreService(db, DedupPolicy(DedupConfig(window_seconds=2.0)))

    svc.save_event(ev(run, 1, 0, [di()]))
    svc.save_event(ev(run, 2, 0.5, [di()]))   # duplicado
    svc.save_event(ev(run, 3, 5.0, [di()]))   # 5s después: nueva observación

    assert db.query(Detection).count() == 2


def test_c1_sin_politica_se_guardan_todas(db, run):
    svc = DetectionStoreService(db, DedupPolicy(DedupConfig(enabled=False)))

    for i in range(10):
        svc.save_event(ev(run, i, i * 0.1, [di()]))

    assert db.query(Detection).count() == 10   # ninguna se omitió
