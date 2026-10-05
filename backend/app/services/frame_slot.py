"""
Slot de último frame: punto de desacople entre captura y consumidores.

La captura publica aquí cada frame completo y sobrescribe el anterior. No hay
cola: un consumidor lento nunca acumula retraso, simplemente se salta los
frames intermedios y recibe el más reciente.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class FramePacket:
    seq: int
    frame: np.ndarray
    captured_at: float


class FrameSlotClosed(Exception):
    """El slot ya no recibirá más frames."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.code = code


class FrameSlot:
    """
    Buffer de tamaño 1 con número de secuencia y espera asíncrona.

    Descarte controlado: al publicar, el frame anterior se reemplaza. Si ningún
    consumidor llegó a tomarlo, se cuenta como descartado. Así se cumple en todo
    momento: publicados = consumidos + descartados + pendientes (0 o 1).
    """

    CAPACITY = 1

    def __init__(self) -> None:
        self._packet: Optional[FramePacket] = None
        self._seq = 0
        # Secuencia más alta que algún consumidor ya tomó del slot.
        self._consumed_seq = 0
        self._discarded = 0
        self._closed_reason: Optional[str] = None
        self._closed_code = ""
        self._event = asyncio.Event()

    @property
    def latest(self) -> Optional[FramePacket]:
        return self._packet

    @property
    def closed(self) -> bool:
        return self._closed_reason is not None

    @property
    def frames_published(self) -> int:
        return self._seq

    @property
    def frames_discarded(self) -> int:
        """Frames reemplazados antes de que algún consumidor los tomara."""
        return self._discarded

    @property
    def frames_pending(self) -> int:
        """1 si el frame retenido aún no lo ha tomado ningún consumidor."""
        packet = self._packet
        return 1 if packet is not None and packet.seq > self._consumed_seq else 0

    @property
    def frames_consumed(self) -> int:
        """Frames distintos que tomó al menos un consumidor."""
        return self._seq - self._discarded - self.frames_pending

    def stats(self) -> dict:
        return {
            "capacity": self.CAPACITY,
            "frames_retained": 0 if self._packet is None else 1,
            "frames_published": self.frames_published,
            "frames_consumed": self.frames_consumed,
            "frames_discarded": self.frames_discarded,
        }

    def publish(self, frame: np.ndarray, captured_at: float) -> FramePacket:
        """Reemplaza el frame actual y despierta a los consumidores en espera."""
        if self.frames_pending:
            self._discarded += 1
        self._seq += 1
        self._packet = FramePacket(seq=self._seq, frame=frame, captured_at=captured_at)
        self._event.set()
        return self._packet

    def close(self, reason: str, code: str = "STREAM_CLOSED") -> None:
        """Marca el fin de la captura; los consumidores reciben FrameSlotClosed."""
        if self._closed_reason is None:
            self._closed_reason = reason
            self._closed_code = code
        self._event.set()

    async def next(self, after_seq: int = 0) -> FramePacket:
        """
        Retorna el frame más reciente con secuencia mayor a `after_seq`.

        Raises:
            FrameSlotClosed: la captura terminó y no hay un frame más nuevo.
        """
        while True:
            packet = self._packet
            if packet is not None and packet.seq > after_seq:
                self._consumed_seq = max(self._consumed_seq, packet.seq)
                return packet
            if self._closed_reason is not None:
                raise FrameSlotClosed(self._closed_reason, self._closed_code)
            self._event.clear()
            await self._event.wait()
