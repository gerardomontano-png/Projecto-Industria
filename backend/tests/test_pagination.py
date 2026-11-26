"""
Pruebas de paginación, ordenamiento y límites de consulta — J05.

Las primeras verifican el módulo `query_pagination` de forma aislada; las
siguientes lo verifican a través de la consulta real de eventos
(`DetectionStoreService.query`), con una base SQLite en memoria.

Criterios cubiertos:
  C1  Las páginas son estables y respetan los límites.
  C2  Los filtros inválidos producen errores controlados.
  C3  Las consultas no devuelven conjuntos ilimitados.

Ejecutar:
    cd backend
    python -m pytest tests/test_pagination.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, create_db_engine
from app.db.models import Camera, ProcessingRun, RunKind, SourceType
from app.services.detection_schemas import (
    DetectionEventInput,
    DetectionInput,
    DetectionValidationError,
    EventQuery,
)
from app.services.detection_store import DetectionStoreService
from app.services.query_pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PaginationError,
    SortDirection,
    SortField,
    SortOrder,
    decode_cursor,
    encode_cursor,
    normalize_limit,
    normalize_offset,
    resolve_sort,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


# ── El módulo de paginación, aislado ─────────────────────────────────────────

def test_normalize_limit_usa_el_defecto_y_el_tope():
    assert normalize_limit(None) == DEFAULT_PAGE_SIZE
    assert normalize_limit(10) == 10
    assert normalize_limit(MAX_PAGE_SIZE) == MAX_PAGE_SIZE


@pytest.mark.parametrize("valor", [0, -1, MAX_PAGE_SIZE + 1, 100_000, True, 3.5])
def test_normalize_limit_rechaza_invalidos(valor):
    with pytest.raises(PaginationError) as info:
        normalize_limit(valor)
    assert info.value.field == "limit"


def test_normalize_offset():
    assert normalize_offset(None) == 0
    assert normalize_offset(25) == 25
    with pytest.raises(PaginationError):
        normalize_offset(-1)


def test_resolve_sort_lista_blanca():
    campos = {
        "captured_at": SortField("captured_at", object()),
        "id": SortField("id", object(), is_unique=True),
    }
    defecto = SortOrder(campos["captured_at"], SortDirection.DESC)

    assert resolve_sort(None, None, campos, defecto) is defecto

    orden = resolve_sort("id", "asc", campos, defecto)
    assert orden.field.name == "id" and orden.direction == SortDirection.ASC

    with pytest.raises(PaginationError) as info:
        resolve_sort("password", None, campos, defecto)  # campo no permitido
    assert info.value.field == "sort_by"

    with pytest.raises(PaginationError) as info:
        resolve_sort(None, "arriba", campos, defecto)   # dirección inválida
    assert info.value.field == "sort_dir"


def test_cursor_ida_y_vuelta():
    valor = T0 + timedelta(hours=3)
    cursor = encode_cursor(valor, "evento-123")
    recuperado, row_id = decode_cursor(cursor)
    assert recuperado == valor
    assert row_id == "evento-123"


def test_cursor_corrupto_es_error_controlado():
    for malo in ("no-es-base64!!", "", "YWJj"):  # texto, vacío, base64 sin estructura
        with pytest.raises(PaginationError) as info:
            decode_cursor(malo)
        assert info.value.field == "cursor"


# ── A través de la consulta real ─────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def svc(db) -> DetectionStoreService:
    return DetectionStoreService(db)


@pytest.fixture
def muchos_eventos(db, svc):
    """25 eventos en horas consecutivas, para probar paginación y orden."""
    cam = Camera(name="L1", source="0", source_type=SourceType.USB)
    run = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="m", created_at=T0)
    run.start(at=T0)
    db.add(cam)
    db.flush()
    for i in range(25):
        svc.save_event(DetectionEventInput(
            run_id=run.id, frame_seq=i,
            captured_at=T0 + timedelta(hours=i),
            detections=[DetectionInput(label="pieza", confidence=0.9, class_id=1,
                                       x1=0, y1=0, x2=10, y2=10)],
        ))
    return run.id


# ── C1: páginas estables y dentro de los límites ─────────────────────────────

def test_c1_paginacion_por_offset_recorre_todo_sin_repetir(svc, muchos_eventos):
    vistos = []
    offset = 0
    while True:
        page = svc.query(EventQuery(limit=10, offset=offset))
        vistos.extend(e.id for e in page.events)
        if not page.has_more:
            break
        offset += 10

    assert len(vistos) == 25
    assert len(set(vistos)) == 25  # ninguno repetido


def test_c1_paginacion_por_cursor_es_estable_ante_inserciones(svc, muchos_eventos, db):
    """
    El cursor sigue una posición exacta. Si se insertan eventos nuevos entre
    página y página, no se repiten ni se saltan los ya vistos.
    """
    run_id = muchos_eventos
    primera = svc.query(EventQuery(limit=10))
    assert primera.next_cursor is not None
    vistos = {e.id for e in primera.events}

    # Llega un evento nuevo MÁS RECIENTE (iría al inicio con orden descendente)
    svc.save_event(DetectionEventInput(
        run_id=run_id, frame_seq=999, captured_at=T0 + timedelta(hours=100),
        detections=[DetectionInput(label="pieza", confidence=0.9, class_id=1,
                                   x1=0, y1=0, x2=10, y2=10)]))

    # La segunda página sigue el cursor: no reaparece ninguno de la primera
    segunda = svc.query(EventQuery(limit=10, cursor=primera.next_cursor))
    assert vistos.isdisjoint({e.id for e in segunda.events})


def test_c1_cursor_recorre_el_total_una_sola_vez(svc, muchos_eventos):
    vistos = []
    cursor = None
    for _ in range(10):  # tope de seguridad
        page = svc.query(EventQuery(limit=7, cursor=cursor))
        vistos.extend(e.id for e in page.events)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert len(vistos) == 25
    assert len(set(vistos)) == 25


def test_c1_orden_por_defecto_es_fecha_descendente(svc, muchos_eventos):
    page = svc.query(EventQuery(limit=5))
    fechas = [e.captured_at for e in page.events]
    assert fechas == sorted(fechas, reverse=True)
    assert page.sort_by == "captured_at" and page.sort_dir == "desc"


def test_c1_orden_configurable(svc, muchos_eventos):
    asc = svc.query(EventQuery(limit=5, sort_by="frame_seq", sort_dir="asc"))
    assert [e.frame_seq for e in asc.events] == [0, 1, 2, 3, 4]

    desc = svc.query(EventQuery(limit=5, sort_by="frame_seq", sort_dir="desc"))
    assert [e.frame_seq for e in desc.events] == [24, 23, 22, 21, 20]


def test_c1_el_orden_desempata_de_forma_estable(svc, db):
    """Varios eventos con la MISMA fecha: el orden sigue siendo determinista."""
    cam = Camera(name="L1", source="0", source_type=SourceType.USB)
    run = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="m", created_at=T0)
    run.start(at=T0)
    db.add(cam)
    db.flush()
    misma_hora = T0 + timedelta(hours=1)
    for i in range(10):
        svc.save_event(DetectionEventInput(
            run_id=run.id, frame_seq=i, captured_at=misma_hora,
            detections=[DetectionInput(label="x", confidence=0.5, class_id=1,
                                       x1=0, y1=0, x2=1, y2=1)]))

    # Dos consultas idénticas devuelven exactamente el mismo orden
    una = [e.id for e in svc.query(EventQuery(limit=100)).events]
    dos = [e.id for e in svc.query(EventQuery(limit=100)).events]
    assert una == dos
    # Y paginar por cursor no repite ni salta
    vistos, cursor = [], None
    for _ in range(10):
        page = svc.query(EventQuery(limit=3, cursor=cursor))
        vistos.extend(e.id for e in page.events)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert sorted(vistos) == sorted(una)


# ── C2: filtros y parámetros inválidos ───────────────────────────────────────

def test_c2_ordenar_por_un_campo_no_permitido(svc, muchos_eventos):
    with pytest.raises(PaginationError) as info:
        svc.query(EventQuery(sort_by="credential_ref"))
    assert info.value.field == "sort_by"


def test_c2_direccion_invalida(svc, muchos_eventos):
    with pytest.raises(PaginationError) as info:
        svc.query(EventQuery(sort_by="captured_at", sort_dir="ascendente"))
    assert info.value.field == "sort_dir"


def test_c2_cursor_corrupto_en_la_consulta(svc, muchos_eventos):
    with pytest.raises(PaginationError) as info:
        svc.query(EventQuery(cursor="basura-que-no-es-cursor"))
    assert info.value.field == "cursor"


def test_c2_periodo_invertido(svc):
    with pytest.raises(DetectionValidationError) as info:
        svc.query(EventQuery(start=T0 + timedelta(hours=1), end=T0))
    assert info.value.field == "period"


# ── C3: nunca un conjunto ilimitado ──────────────────────────────────────────

def test_c3_sin_limit_se_aplica_el_valor_por_defecto(svc, db):
    cam = Camera(name="L1", source="0", source_type=SourceType.USB)
    run = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="m", created_at=T0)
    run.start(at=T0)
    db.add(cam)
    db.flush()
    # Más eventos que el tamaño de página por defecto
    for i in range(DEFAULT_PAGE_SIZE + 20):
        svc.save_event(DetectionEventInput(
            run_id=run.id, frame_seq=i, captured_at=T0 + timedelta(minutes=i),
            detections=[]))

    page = svc.query(EventQuery())  # sin pedir limit
    assert len(page.events) == DEFAULT_PAGE_SIZE   # no devolvió todo
    assert page.total == DEFAULT_PAGE_SIZE + 20     # pero informa el total real
    assert page.has_more is True


def test_c3_un_limit_enorme_se_rechaza_no_se_recorta(svc, muchos_eventos):
    # No se "acomoda" silenciosamente al máximo: se avisa que es inválido
    with pytest.raises(PaginationError) as info:
        svc.query(EventQuery(limit=1_000_000))
    assert info.value.field == "limit"
    assert str(MAX_PAGE_SIZE) in str(info.value)


def test_c3_el_maximo_es_el_tope_real(svc, db):
    cam = Camera(name="L1", source="0", source_type=SourceType.USB)
    run = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="m", created_at=T0)
    run.start(at=T0)
    db.add(cam)
    db.flush()
    for i in range(MAX_PAGE_SIZE + 50):
        svc.save_event(DetectionEventInput(
            run_id=run.id, frame_seq=i, captured_at=T0 + timedelta(seconds=i),
            detections=[]))

    page = svc.query(EventQuery(limit=MAX_PAGE_SIZE))
    assert len(page.events) == MAX_PAGE_SIZE       # entrega justo el máximo
    assert page.has_more is True                    # y no más que eso
