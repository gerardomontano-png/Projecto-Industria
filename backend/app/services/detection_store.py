"""
Persistencia y consulta de eventos de detección (J04).

Dos responsabilidades:

  - guardar un evento con sus detecciones, validado contra el modelo aprobado
    y verificando que la corrida exista y que la cámara del evento sea la suya;
  - consultar eventos con filtros combinables por cámara, clase, confianza y
    periodo, con paginación y conteo total.

El servicio no hace commit: trabaja sobre la sesión que recibe, igual que los
repositorios y el servicio de fuentes de J03.

Nota sobre el filtro de detecciones: cuando se filtra por clase, etiqueta o
confianza, un evento aparece si tiene *al menos una* detección que cumple. Las
detecciones que trae cada evento en la respuesta son todas las del evento, no
solo las que pasaron el filtro, para no dar una imagen falsa del frame. Esto se
documenta en el método `query`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Camera,
    Detection,
    DetectionEvent,
    ProcessingRun,
)
from app.services.detection_schemas import (
    DetectionEventInput,
    DetectionEventRead,
    DetectionValidationError,
    EventPage,
    EventQuery,
)
from app.services.query_pagination import (
    SortDirection,
    SortField,
    SortOrder,
    decode_cursor,
    encode_cursor,
)

# Campos por los que se permite ordenar los eventos (lista blanca de J05).
# captured_at es el orden natural de un historial; el id desempata y es único.
_SORT_FIELDS: dict[str, SortField] = {
    "captured_at": SortField("captured_at", DetectionEvent.captured_at),
    "processed_at": SortField("processed_at", DetectionEvent.processed_at),
    "frame_seq": SortField("frame_seq", DetectionEvent.frame_seq),
    "id": SortField("id", DetectionEvent.id, is_unique=True),
}
_DEFAULT_SORT = SortOrder(_SORT_FIELDS["captured_at"], SortDirection.DESC)


class DetectionStoreError(Exception):
    code = "DETECTION_STORE_ERROR"


class RunNotFoundError(DetectionStoreError):
    code = "RUN_NOT_FOUND"


class DuplicateEventError(DetectionStoreError):
    """Ya existe un evento para ese frame en esa corrida."""

    code = "EVENT_DUPLICATE"


class DetectionStoreService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Guardar ──────────────────────────────────────────────────────────────

    def save_event(self, data: DetectionEventInput) -> DetectionEventRead:
        """
        Guarda un evento con sus detecciones.

        Valida el evento contra el modelo aprobado, resuelve la cámara desde la
        corrida (para no confiar en un camera_id enviado por fuera) y rechaza un
        segundo evento para el mismo frame de la misma corrida.

        Raises:
            DetectionValidationError: el evento o una detección es inválido.
            RunNotFoundError: la corrida no existe.
            DuplicateEventError: ya hay un evento para ese frame.
        """
        clean = data.validated()

        run = self.session.get(ProcessingRun, clean.run_id)
        if run is None:
            raise RunNotFoundError(f"No existe la corrida '{clean.run_id}'.")

        ya_existe = self.session.scalar(
            select(exists().where(
                DetectionEvent.run_id == clean.run_id,
                DetectionEvent.frame_seq == clean.frame_seq,
            ))
        )
        if ya_existe:
            raise DuplicateEventError(
                f"Ya hay un evento para el frame {clean.frame_seq} de la corrida."
            )

        event = DetectionEvent(
            run_id=clean.run_id,
            camera_id=run.camera_id,  # la cámara se toma de la corrida, no del input
            frame_seq=clean.frame_seq,
            captured_at=clean.captured_at,
            processed_at=clean.processed_at,
            frame_width=clean.frame_width,
            frame_height=clean.frame_height,
            roi=clean.roi,
            detections=[d.to_model() for d in clean.detections],
        )
        self.session.add(event)
        self.session.flush()
        return DetectionEventRead.from_model(event)

    # ── Consultar ────────────────────────────────────────────────────────────

    def query(self, q: EventQuery) -> EventPage:
        """
        Consulta eventos con filtros combinables (todos opcionales, unidos con Y):

          - camera_id, run_id: igualdad exacta;
          - start / end: por fecha de captura (inicio inclusivo, fin exclusivo);
          - label, class_id, min_confidence: el evento aparece si tiene al menos
            una detección que cumple.

        Paginación (J05): por offset, o por cursor estable si se envía uno. El
        orden se elige con sort_by/sort_dir entre una lista blanca; por defecto,
        fecha de captura descendente. Cada evento devuelto trae TODAS sus
        detecciones, no solo las que pasaron el filtro.
        """
        from app.services.query_pagination import resolve_sort

        clean = q.validated()
        order = resolve_sort(clean.sort_by, clean.sort_dir, _SORT_FIELDS, _DEFAULT_SORT)

        base = self._apply_filters(select(DetectionEvent), clean)
        total = self.session.scalar(
            self._apply_filters(select(func.count(DetectionEvent.id.distinct())), clean)
        ) or 0

        # Orden: el campo pedido y, para desempatar de forma estable, el id.
        col = order.field.column
        tie = DetectionEvent.id
        if order.direction == SortDirection.DESC:
            order_by = [col.desc(), tie.desc()]
        else:
            order_by = [col.asc(), tie.asc()]

        stmt = self._apply_filters(select(DetectionEvent), clean)

        usa_cursor = clean.cursor is not None
        if usa_cursor:
            # Paginación por cursor: "sigue después de esta posición exacta".
            sort_value, last_id = decode_cursor(clean.cursor)
            stmt = stmt.where(self._after_cursor(order, sort_value, last_id))
            stmt = stmt.order_by(*order_by).limit(clean.limit)
        else:
            stmt = stmt.order_by(*order_by).offset(clean.offset).limit(clean.limit)

        stmt = stmt.options(selectinload(DetectionEvent.detections))
        eventos = list(self.session.scalars(stmt).unique())

        # next_cursor se ofrece siempre que la página se llenó y hay más por venir:
        # permite pasar a la paginación estable por cursor desde cualquier punto.
        hay_mas = (clean.offset + len(eventos)) < total if not usa_cursor else len(eventos) == clean.limit
        next_cursor = None
        if hay_mas and eventos:
            ultimo = eventos[-1]
            next_cursor = encode_cursor(getattr(ultimo, order.field.name), ultimo.id)

        return EventPage(
            events=[DetectionEventRead.from_model(e) for e in eventos],
            total=total, limit=clean.limit, offset=clean.offset,
            next_cursor=next_cursor,
            sort_by=order.field.name, sort_dir=order.direction.value,
        )

    def _after_cursor(self, order: SortOrder, sort_value, last_id: str):
        """Condición 'después del cursor', respetando el orden y desempatando por id."""
        col = order.field.column
        if order.direction == SortDirection.DESC:
            # Orden descendente: lo siguiente es MENOR, o igual con id menor
            return or_(col < sort_value, and_(col == sort_value, DetectionEvent.id < last_id))
        return or_(col > sort_value, and_(col == sort_value, DetectionEvent.id > last_id))

    def get_event(self, event_id: str) -> Optional[DetectionEventRead]:
        ev = self.session.get(DetectionEvent, event_id)
        return DetectionEventRead.from_model(ev) if ev is not None else None

    def _apply_filters(self, stmt, q: EventQuery):
        if q.camera_id is not None:
            stmt = stmt.where(DetectionEvent.camera_id == q.camera_id)
        if q.run_id is not None:
            stmt = stmt.where(DetectionEvent.run_id == q.run_id)
        if q.start is not None:
            stmt = stmt.where(DetectionEvent.captured_at >= q.start)
        if q.end is not None:
            stmt = stmt.where(DetectionEvent.captured_at < q.end)

        if q.filters_detections:
            # El evento califica si EXISTE una detección suya que cumpla los
            # filtros de detección. Un EXISTS correlacionado evita duplicar
            # filas del evento cuando varias detecciones cumplen.
            cond = [Detection.event_id == DetectionEvent.id]
            if q.label is not None:
                cond.append(Detection.label == q.label)
            if q.class_id is not None:
                cond.append(Detection.class_id == q.class_id)
            if q.min_confidence is not None:
                cond.append(Detection.confidence >= q.min_confidence)
            stmt = stmt.where(exists().where(*cond))
        return stmt
