"""Repositorio de cámaras."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.db.models import Camera, CameraStatus, SourceType
from app.db.repositories.base import Repository


class CameraRepository(Repository[Camera]):
    model = Camera

    def get_by_name(self, name: str) -> Optional[Camera]:
        return self.session.scalar(select(Camera).where(Camera.name == name))

    def get_by_source(self, source_type: SourceType, source: str) -> Optional[Camera]:
        return self.session.scalar(
            select(Camera).where(
                Camera.source_type == source_type, Camera.source == source
            )
        )

    def list_by_status(self, status: CameraStatus) -> list[Camera]:
        return list(
            self.session.scalars(
                select(Camera).where(Camera.status == status).order_by(Camera.name)
            )
        )

    def list_active(self) -> list[Camera]:
        """Cámaras disponibles para procesar, ordenadas por nombre."""
        return self.list_by_status(CameraStatus.ACTIVE)
