"""
Modelo de datos de cámaras, procesamiento y detecciones (J01).

Cuatro entidades, de lo general a lo particular:

    Camera ──< ProcessingRun ──< DetectionEvent ──< Detection

  - Camera: una cámara registrada (USB, RTSP o archivo de video).
  - ProcessingRun: una corrida de procesamiento sobre una cámara (un stream,
    un stream con inferencia o el análisis de una imagen), con su estado y
    sus fechas.
  - DetectionEvent: lo que se detectó en un frame concreto de una corrida.
  - Detection: cada objeto detectado dentro de ese frame (etiqueta,
    confianza y caja).

La integridad no depende solo del código de Python: las reglas importantes
también están en la base de datos como llaves foráneas, restricciones únicas y
restricciones CHECK, de modo que ni un script externo pueda dejar datos
inconsistentes.

Credenciales: la tabla de cámaras guarda la fuente *pública* (sin usuario ni
contraseña) y, si la cámara las necesita, solo el *nombre* del secreto donde
viven (`credential_ref`, por ejemplo una variable de entorno). Ningún campo de
respuesta o de historial acepta credenciales: los validadores lo rechazan
antes de guardar.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum as SAEnum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, UTCDateTime, new_id, utc_now


# ── Enumeraciones ─────────────────────────────────────────────────────────────

class SourceType(str, Enum):
    USB = "usb"
    RTSP = "rtsp"
    FILE = "file"


class CameraStatus(str, Enum):
    ACTIVE = "active"        # disponible para procesar
    INACTIVE = "inactive"    # registrada, pero fuera de servicio temporalmente
    RETIRED = "retired"      # dada de baja; se conserva por su historial


class RunKind(str, Enum):
    STREAM = "stream"                      # /ws/stream, sin inferencia
    INFERENCE_STREAM = "inference_stream"  # /ws/inference-stream
    IMAGE = "image"                        # /inference/* sobre una imagen


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Tupla (y no conjunto) para que el SQL de las restricciones sea siempre idéntico
TERMINAL_RUN_STATUSES = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)

# Transiciones permitidas del estado de una corrida
RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def _enum_column(enum_cls: type[Enum], name: str) -> SAEnum:
    """Enum guardado como texto, con una restricción CHECK de valores válidos."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
        length=20,
    )


def _sql_list(values) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


# ── Errores ───────────────────────────────────────────────────────────────────

class InvalidTransitionError(ValueError):
    """Cambio de estado no permitido para una corrida."""


# El manejo de credenciales vive en una sola salvaguarda central (J07).
from app.services.credential_guard import (  # noqa: E402
    CredentialLeakError,
    find_credentials as find_credential,
    is_valid_credential_ref,
    reject_credentials as _reject_credentials,
)


# ── Cámaras ───────────────────────────────────────────────────────────────────

class Camera(Base):
    """Cámara registrada en el sistema."""

    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        _enum_column(SourceType, "source_type"), nullable=False
    )
    # Fuente pública: índice USB, ruta de archivo o URL RTSP *sin* credenciales
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    # Nombre del secreto (p. ej. una variable de entorno) con las credenciales
    credential_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[CameraStatus] = mapped_column(
        _enum_column(CameraStatus, "camera_status"),
        nullable=False,
        default=CameraStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list["ProcessingRun"]] = relationship(
        back_populates="camera", passive_deletes="all"
    )

    __table_args__ = (
        UniqueConstraint("name"),
        UniqueConstraint("source_type", "source"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("length(trim(source)) > 0", name="source_not_blank"),
        CheckConstraint("updated_at >= created_at", name="updated_after_created"),
        Index(None, "status"),
    )

    @validates("source")
    def _validate_source(self, _key: str, value: str) -> str:
        return _reject_credentials("source", value)

    @validates("credential_ref")
    def _validate_credential_ref(self, _key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_valid_credential_ref(value):
            raise ValueError(
                "credential_ref debe ser el nombre de un secreto en mayúsculas, "
                "por ejemplo CAMARA_LINEA1_RTSP; nunca la credencial misma."
            )
        return value


# ── Corridas de procesamiento ─────────────────────────────────────────────────

class ProcessingRun(Base):
    """Una corrida de procesamiento sobre una cámara."""

    __tablename__ = "processing_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[RunKind] = mapped_column(_enum_column(RunKind, "run_kind"), nullable=False)
    # Modelo resuelto (aunque el cliente haya pedido el modelo por defecto)
    model_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Parámetros de la corrida: conf, iou, ROI, infer_every_n_frames...
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[RunStatus] = mapped_column(
        _enum_column(RunStatus, "run_status"), nullable=False, default=RunStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    frames_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    camera: Mapped[Camera] = relationship(back_populates="runs")
    events: Mapped[list["DetectionEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # Permite que los eventos referencien (corrida, cámara) como par válido
        UniqueConstraint("id", "camera_id"),
        CheckConstraint("frames_processed >= 0", name="frames_processed_non_negative"),
        CheckConstraint(
            f"(kind = '{RunKind.STREAM.value}' AND model_id IS NULL) OR "
            f"(kind <> '{RunKind.STREAM.value}' AND model_id IS NOT NULL)",
            name="model_matches_kind",
        ),
        CheckConstraint(
            f"(status = '{RunStatus.PENDING.value}' AND started_at IS NULL) OR "
            f"(status IN ({_sql_list([RunStatus.RUNNING, RunStatus.COMPLETED, RunStatus.FAILED])}) "
            "AND started_at IS NOT NULL) OR "
            f"(status = '{RunStatus.CANCELLED.value}')",
            name="started_matches_status",
        ),
        CheckConstraint(
            f"(status IN ({_sql_list(TERMINAL_RUN_STATUSES)}) AND finished_at IS NOT NULL) OR "
            f"(status NOT IN ({_sql_list(TERMINAL_RUN_STATUSES)}) AND finished_at IS NULL)",
            name="finished_matches_status",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="started_after_created"
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        CheckConstraint(
            f"(status = '{RunStatus.FAILED.value}' AND error_code IS NOT NULL) OR "
            f"(status <> '{RunStatus.FAILED.value}' AND error_code IS NULL AND error_message IS NULL)",
            name="error_only_when_failed",
        ),
        Index(None, "camera_id", "created_at"),
        Index(None, "status"),
    )

    @validates("parameters")
    def _validate_parameters(self, _key: str, value: Optional[dict]) -> dict:
        return _reject_credentials("parameters", value or {})

    @validates("error_message")
    def _validate_error_message(self, _key: str, value: Optional[str]) -> Optional[str]:
        return _reject_credentials("error_message", value)

    # Transiciones de estado: la única forma recomendada de cambiarlo

    def _move_to(self, target: RunStatus) -> None:
        current = self.status or RunStatus.PENDING
        if target not in RUN_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"La corrida no puede pasar de '{current.value}' a '{target.value}'."
            )
        self.status = target

    def start(self, at: Optional[datetime] = None) -> None:
        self._move_to(RunStatus.RUNNING)
        self.started_at = at or utc_now()

    def complete(self, at: Optional[datetime] = None) -> None:
        self._move_to(RunStatus.COMPLETED)
        self.finished_at = at or utc_now()

    def fail(self, code: str, message: Optional[str] = None, at: Optional[datetime] = None) -> None:
        self._move_to(RunStatus.FAILED)
        self.error_code = code
        self.error_message = message
        self.finished_at = at or utc_now()

    def cancel(self, at: Optional[datetime] = None) -> None:
        self._move_to(RunStatus.CANCELLED)
        self.finished_at = at or utc_now()


# ── Eventos de detección ──────────────────────────────────────────────────────

class DetectionEvent(Base):
    """Resultado de procesar un frame concreto de una corrida."""

    __tablename__ = "detection_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Redundante a propósito para consultar por cámara y fecha sin unir tablas;
    # la llave compuesta garantiza que coincide con la cámara de la corrida.
    camera_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Número de secuencia del frame en la captura (el `seq` del stream)
    frame_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    frame_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frame_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ROI aplicado, en coordenadas del frame completo: [[x, y], ...]
    roi: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    run: Mapped[ProcessingRun] = relationship(back_populates="events")
    detections: Mapped[list["Detection"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "camera_id"],
            ["processing_runs.id", "processing_runs.camera_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "frame_seq"),
        CheckConstraint("frame_seq >= 0", name="frame_seq_non_negative"),
        CheckConstraint("processed_at >= captured_at", name="processed_after_captured"),
        CheckConstraint(
            "(frame_width IS NULL AND frame_height IS NULL) OR "
            "(frame_width > 0 AND frame_height > 0)",
            name="frame_size_positive",
        ),
        Index(None, "camera_id", "captured_at"),
    )


# ── Detecciones ───────────────────────────────────────────────────────────────

class Detection(Base):
    """Un objeto detectado dentro de un frame."""

    __tablename__ = "detections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("detection_events.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    class_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # Caja en píxeles del frame completo
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    x2: Mapped[float] = mapped_column(Float, nullable=False)
    y2: Mapped[float] = mapped_column(Float, nullable=False)
    # Datos extra del modelo (p. ej. texto de OCR); nunca credenciales
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    event: Mapped[DetectionEvent] = relationship(back_populates="detections")

    __table_args__ = (
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
        CheckConstraint("class_id IS NULL OR class_id >= 0", name="class_id_non_negative"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_in_range"),
        CheckConstraint("x1 >= 0 AND y1 >= 0", name="box_origin_non_negative"),
        CheckConstraint("x2 > x1 AND y2 > y1", name="box_has_area"),
        Index(None, "event_id"),
        Index(None, "label"),
    )

    @validates("attributes")
    def _validate_attributes(self, _key: str, value: Optional[dict]) -> Optional[dict]:
        return _reject_credentials("attributes", value)
