"""
Contrato de entrada de la región de interés (ROI) — coordenadas absolutas.

Una ROI delimita una parte del frame sobre la que correr la inferencia. Este
módulo fija y valida ese contrato de entrada, con coordenadas **absolutas**
`x1, y1, x2, y2` referidas al frame original (la esquina superior izquierda es
`(x1, y1)`, la inferior derecha `(x2, y2)`).

Reglas del contrato:

  - Solo se aceptan valores numéricos **finitos** (un NaN o un infinito se
    rechazan).
  - Debe cumplirse `x1 < x2` y `y1 < y2`, y el área debe ser positiva. Una ROI
    con coordenadas invertidas o área nula se **rechaza**; no se corrige en
    silencio.
  - Si la ROI excede las dimensiones del frame, se **rechaza** por defecto. Con
    `clamp=True` se **limita** al borde del frame en vez de rechazarla (las dos
    salidas controladas que pide el contrato).
  - La ausencia de ROI (ningún valor) representa el **frame completo**.

Lo que este módulo NO hace: no recorta la imagen (eso es de image_service), no
convierte coordenadas (son absolutas de entrada a salida), y no tiene nada de
interfaz. Solo valida y normaliza el contrato.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


class ROIValidationError(ValueError):
    """La ROI recibida no cumple el contrato de entrada."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# Códigos estables del contrato: un cliente puede ramificar sobre ellos.
ROI_NOT_FINITE = "ROI_NOT_FINITE"          # algún valor no es un número finito
ROI_INCOMPLETE = "ROI_INCOMPLETE"          # se dieron algunos valores pero no los cuatro
ROI_NOT_ORDERED = "ROI_NOT_ORDERED"        # x1 >= x2 o y1 >= y2 (incluye área nula)
ROI_OUT_OF_BOUNDS = "ROI_OUT_OF_BOUNDS"    # excede el frame y no se pidió limitar


@dataclass(frozen=True)
class ROI:
    """Una ROI válida en coordenadas absolutas y enteras del frame."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def offset(self) -> tuple[int, int]:
        """Desplazamiento de la ROI respecto al frame, para mapear coordenadas de vuelta."""
        return (self.x1, self.y1)

    def as_xywh(self) -> list[int]:
        """La ROI en formato [x, y, width, height], como lo espera image_service."""
        return [self.x1, self.y1, self.width, self.height]

    def to_dict(self) -> dict:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


def _finite_number(value, name: str) -> float:
    """Convierte a float validando que sea un número finito (ni NaN ni infinito)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ROIValidationError(
            ROI_NOT_FINITE, f"{name} debe ser un número; se recibió {type(value).__name__}."
        )
    v = float(value)
    if not math.isfinite(v):
        raise ROIValidationError(
            ROI_NOT_FINITE, f"{name} debe ser un número finito (no NaN ni infinito)."
        )
    return v


def validate_roi(
    x1, y1, x2, y2,
    *,
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
    clamp: bool = False,
) -> ROI:
    """
    Valida y normaliza una ROI en coordenadas absolutas.

    Args:
        x1, y1, x2, y2: coordenadas absolutas del frame.
        frame_width, frame_height: dimensiones del frame, para comprobar los
            límites. Si son None, no se comprueban los límites (solo el orden).
        clamp: si True, una ROI que excede el frame se limita al borde en vez
            de rechazarse.

    Returns:
        Una ROI válida (y limitada al frame si clamp y hacía falta).

    Raises:
        ROIValidationError: con un código estable según la regla incumplida.
    """
    fx1 = _finite_number(x1, "x1")
    fy1 = _finite_number(y1, "y1")
    fx2 = _finite_number(x2, "x2")
    fy2 = _finite_number(y2, "y2")

    # Coordenadas absolutas enteras: el píxel es la unidad del frame.
    ix1, iy1, ix2, iy2 = int(fx1), int(fy1), int(fx2), int(fy2)

    # Orden y área positiva: NO se corrige una ROI invertida; se rechaza.
    if ix1 >= ix2 or iy1 >= iy2:
        raise ROIValidationError(
            ROI_NOT_ORDERED,
            f"La ROI debe cumplir x1 < x2 y y1 < y2 (se recibió "
            f"x1={ix1}, y1={iy1}, x2={ix2}, y2={iy2}); el área debe ser positiva.",
        )

    if frame_width is not None and frame_height is not None:
        dentro = ix1 >= 0 and iy1 >= 0 and ix2 <= frame_width and iy2 <= frame_height
        if not dentro:
            if not clamp:
                raise ROIValidationError(
                    ROI_OUT_OF_BOUNDS,
                    f"La ROI excede el frame de {frame_width}x{frame_height} "
                    f"(se recibió x1={ix1}, y1={iy1}, x2={ix2}, y2={iy2}). "
                    "Use clamp para limitarla al borde.",
                )
            # Limitar al borde del frame
            ix1 = max(0, min(ix1, frame_width))
            iy1 = max(0, min(iy1, frame_height))
            ix2 = max(0, min(ix2, frame_width))
            iy2 = max(0, min(iy2, frame_height))
            # Tras limitar, la ROI podría quedar sin área (p. ej. estaba entera
            # fuera del frame): eso es un rechazo controlado.
            if ix1 >= ix2 or iy1 >= iy2:
                raise ROIValidationError(
                    ROI_OUT_OF_BOUNDS,
                    "La ROI queda sin área tras limitarla al frame: está "
                    "completamente fuera de la imagen.",
                )

    return ROI(ix1, iy1, ix2, iy2)


def parse_roi_request(
    x1, y1, x2, y2,
    *,
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
    clamp: bool = False,
) -> Optional[ROI]:
    """
    Interpreta los cuatro parámetros de ROI de una petición.

    - Si los cuatro son None, no hay ROI: representa el frame completo (None).
    - Si hay algunos pero no los cuatro, es un error (`ROI_INCOMPLETE`).
    - Si están los cuatro, se validan con `validate_roi`.
    """
    dados = [x1, y1, x2, y2]
    if all(v is None for v in dados):
        return None  # sin ROI = frame completo
    if any(v is None for v in dados):
        raise ROIValidationError(
            ROI_INCOMPLETE,
            "Para una ROI se requieren los cuatro valores: x1, y1, x2, y2.",
        )
    return validate_roi(
        x1, y1, x2, y2,
        frame_width=frame_width, frame_height=frame_height, clamp=clamp,
    )
