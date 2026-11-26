"""Repositorios de eventos de detección y de detecciones."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

from app.db.models import Detection, DetectionEvent
from app.db.repositories.base import Repository


class DetectionEventRepository(Repository[DetectionEvent]):
    model = DetectionEvent

    def list_for_run(self, run_id: str) -> list[DetectionEvent]:
        """Eventos de una corrida, en orden de captura."""
        return list(
            self.session.scalars(
                select(DetectionEvent)
                .where(DetectionEvent.run_id == run_id)
                .order_by(DetectionEvent.frame_seq)
            )
        )

    def list_for_camera_between(
        self, camera_id: str, start: datetime, end: datetime
    ) -> list[DetectionEvent]:
        """
        Eventos de una cámara en un rango de fechas.

        Es la consulta de historial más frecuente; se apoya en el índice
        ix_detection_events_camera_id_captured_at.
        """
        return list(
            self.session.scalars(
                select(DetectionEvent)
                .where(
                    DetectionEvent.camera_id == camera_id,
                    DetectionEvent.captured_at >= start,
                    DetectionEvent.captured_at < end,
                )
                .order_by(DetectionEvent.captured_at)
            )
        )


class DetectionRepository(Repository[Detection]):
    model = Detection

    def list_for_event(self, event_id: str) -> list[Detection]:
        return list(
            self.session.scalars(
                select(Detection).where(Detection.event_id == event_id)
            )
        )

    def count_by_label_for_run(self, run_id: str) -> dict[str, int]:
        """Cuántas detecciones de cada etiqueta hubo en una corrida."""
        stmt = (
            select(Detection.label, func.count())
            .join(DetectionEvent, Detection.event_id == DetectionEvent.id)
            .where(DetectionEvent.run_id == run_id)
            .group_by(Detection.label)
            .order_by(func.count().desc())
        )
        return {label: total for label, total in self.session.execute(stmt)}
