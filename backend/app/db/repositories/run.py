"""Repositorio de corridas de procesamiento."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.db.models import ProcessingRun, RunStatus, TERMINAL_RUN_STATUSES
from app.db.repositories.base import Repository


class ProcessingRunRepository(Repository[ProcessingRun]):
    model = ProcessingRun

    def history_for_camera(
        self, camera_id: str, *, limit: Optional[int] = 50
    ) -> list[ProcessingRun]:
        """Corridas de una cámara, de la más reciente a la más antigua."""
        stmt = (
            select(ProcessingRun)
            .where(ProcessingRun.camera_id == camera_id)
            .order_by(ProcessingRun.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def list_active(self) -> list[ProcessingRun]:
        """Corridas que aún no terminan (pendientes o en curso)."""
        return list(
            self.session.scalars(
                select(ProcessingRun)
                .where(ProcessingRun.status.notin_(TERMINAL_RUN_STATUSES))
                .order_by(ProcessingRun.created_at)
            )
        )

    def list_by_status(self, status: RunStatus) -> list[ProcessingRun]:
        return list(
            self.session.scalars(
                select(ProcessingRun)
                .where(ProcessingRun.status == status)
                .order_by(ProcessingRun.created_at.desc())
            )
        )
