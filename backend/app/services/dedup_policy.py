"""
Política de deduplicación de detecciones (J06).

El problema: una cámara que mira una pieza quieta genera, frame tras frame, la
misma detección. Guardarlas todas llena la base de registros redundantes que no
aportan información. La política decide cuándo dos detecciones son "la misma
observación repetida" y debe registrarse una sola vez.

Dos cosas se pueden configurar:

  - La VENTANA temporal: dos detecciones solo se consideran repetidas si ocurren
    con menos de `window_seconds` de diferencia. Pasada la ventana, la misma
    pieza vuelve a registrarse (es una observación nueva, no un duplicado del
    frame anterior).
  - El CRITERIO de equivalencia: qué hace que dos detecciones sean "la misma".
    Por defecto: misma cámara, misma clase/etiqueta y cajas que se solapan lo
    suficiente (IoU por encima de un umbral). Cada parte es ajustable.

La política NO borra nada: decide, para una detección entrante, si es un
duplicado de una ya vista en la ventana. Quien guarda (J04) usa esa decisión
para omitir la detección redundante, conservando siempre los eventos distintos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional


class DedupConfigError(ValueError):
    """La configuración de la política es inválida."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True)
class DedupConfig:
    """
    Parámetros de la política. Los valores por defecto son un punto de partida
    razonable para una línea industrial; se ajustan según la cámara y el proceso.
    """

    enabled: bool = True
    # Dos detecciones a más de esta distancia en el tiempo NO son duplicados
    window_seconds: float = 2.0
    # Fracción de solape de las cajas (IoU) para considerarlas la misma posición
    iou_threshold: float = 0.5
    # Si la clase (class_id) debe coincidir para considerar duplicado
    match_class: bool = True
    # Si la etiqueta (label) debe coincidir
    match_label: bool = True

    def validated(self) -> "DedupConfig":
        if self.window_seconds <= 0:
            raise DedupConfigError("window_seconds", "La ventana debe ser mayor que cero.")
        if not (0.0 < self.iou_threshold <= 1.0):
            raise DedupConfigError("iou_threshold", "El umbral de IoU debe estar entre 0 y 1.")
        return self

    @property
    def window(self) -> timedelta:
        return timedelta(seconds=self.window_seconds)


@dataclass(frozen=True)
class _Box:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return (self.x2 - self.x1) * (self.y2 - self.y1)


def iou(a: _Box, b: _Box) -> float:
    """
    Intersección sobre unión de dos cajas: 0 si no se tocan, 1 si son idénticas.

    Es la medida estándar de "qué tanto se solapan". Dos cajas en la misma
    posición dan un IoU cercano a 1; dos cajas lejanas, cercano a 0.
    """
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


@dataclass
class DetectionKey:
    """Los datos de una detección que la política necesita para comparar."""

    camera_id: str
    class_id: Optional[int]
    label: str
    box: tuple[float, float, float, float]

    @property
    def _box(self) -> _Box:
        return _Box(*self.box)


class DedupPolicy:
    """
    Decide si una detección es un duplicado reciente de otra ya vista.

    Mantiene en memoria las últimas detecciones aceptadas por cámara, para
    comparar contra ellas. No toca la base: es una decisión pura.
    """

    def __init__(self, config: Optional[DedupConfig] = None) -> None:
        self.config = (config or DedupConfig()).validated()
        # Por cámara, las detecciones recientes aceptadas: (timestamp, DetectionKey)
        self._recent: dict[str, list[tuple[float, DetectionKey]]] = {}

    def equivalent(self, a: DetectionKey, b: DetectionKey) -> bool:
        """¿Dos detecciones son la misma observación, según el criterio configurado?"""
        if a.camera_id != b.camera_id:
            return False
        if self.config.match_class and a.class_id != b.class_id:
            return False
        if self.config.match_label and a.label != b.label:
            return False
        return iou(a._box, b._box) >= self.config.iou_threshold

    def is_duplicate(self, key: DetectionKey, timestamp: float) -> bool:
        """
        ¿La detección es un duplicado de una ya aceptada dentro de la ventana?

        `timestamp` es el momento de captura, en segundos (monótonos o epoch).
        Si la política está desactivada, nada es duplicado.

        Esta llamada también registra la detección como vista cuando NO es
        duplicado, y descarta de memoria las que ya quedaron fuera de la ventana.
        """
        if not self.config.enabled:
            return False

        ventana = self.config.window_seconds
        recientes = self._recent.setdefault(key.camera_id, [])
        # Olvidar lo que ya salió de la ventana
        vigentes = [(t, k) for t, k in recientes if timestamp - t < ventana]

        for t, visto in vigentes:
            if self.equivalent(key, visto):
                # Es un duplicado: se refresca el tiempo del visto y se omite
                self._recent[key.camera_id] = [
                    (timestamp, k) if k is visto else (t2, k)
                    for t2, k in vigentes
                ]
                return True

        # No es duplicado: se registra como vista
        vigentes.append((timestamp, key))
        self._recent[key.camera_id] = vigentes
        return False

    def reset(self) -> None:
        """Olvida todo lo visto. Útil al iniciar una corrida nueva."""
        self._recent.clear()


def describe_policy(config: DedupConfig) -> str:
    """Texto legible de la política, para logs y documentación en vivo."""
    if not config.enabled:
        return "Deduplicación desactivada: se registran todas las detecciones."
    partes = ["misma cámara"]
    if config.match_class:
        partes.append("misma clase")
    if config.match_label:
        partes.append("misma etiqueta")
    partes.append(f"solape de cajas ≥ {config.iou_threshold:.0%}")
    return (
        f"Se considera duplicado si, dentro de {config.window_seconds:g} s, hay otra "
        f"detección con: {', '.join(partes)}."
    )
