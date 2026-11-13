"""
Repositorios de la capa de persistencia (J02).

Un repositorio reúne, en un solo lugar, las consultas y operaciones sobre una
entidad. El resto del sistema pide cosas al repositorio ("dame las cámaras
activas", "guarda este evento") sin escribir SQL ni consultas de SQLAlchemy
dispersas por el código.

Regla importante: los repositorios **nunca hacen commit**. Reciben la sesión
desde afuera y solo preparan los cambios (add, flush). Quien abrió la sesión
—normalmente `session_scope` o la dependencia de FastAPI— decide cuándo
confirmar. Así, varias operaciones de distintos repositorios pueden
confirmarse o revertirse como una sola unidad de trabajo.
"""

from app.db.repositories.base import Repository
from app.db.repositories.camera import CameraRepository
from app.db.repositories.detection import (
    DetectionEventRepository,
    DetectionRepository,
)
from app.db.repositories.run import ProcessingRunRepository

__all__ = [
    "Repository",
    "CameraRepository",
    "ProcessingRunRepository",
    "DetectionEventRepository",
    "DetectionRepository",
]
