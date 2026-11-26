"""
Resolución de ROI para los endpoints (contrato absoluto).

Puente entre el contrato de ROI (`roi_contract`) y el recorte real de la imagen
(`image_service`). Toma los parámetros `x1,y1,x2,y2` de una petición, valida el
contrato contra las dimensiones del frame y, si la ROI es válida, recorta.

Mantiene el valor de retorno que los endpoints ya esperan hoy —
`(imagen_recortada, roi_en_xywh, offset)` — para que adoptarlo no cambie la
forma de las respuestas. La diferencia es que ahora la validación es el contrato
absoluto de esta tarea: finitos, orden, área positiva y límites del frame.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from app.services.roi_contract import ROI, ROIValidationError, parse_roi_request


def resolve_roi_absolute(
    image: np.ndarray,
    x1=None, y1=None, x2=None, y2=None,
    *,
    clamp: bool = False,
) -> tuple[np.ndarray, Optional[list[int]], tuple[int, int]]:
    """
    Valida la ROI absoluta y recorta la imagen.

    Returns:
        (imagen_recortada, roi_en_[x,y,w,h] o None, offset).
        Sin ROI (los cuatro None), devuelve la imagen completa, roi=None y offset (0,0).

    Raises:
        ROIValidationError: si la ROI incumple el contrato.
    """
    height, width = image.shape[:2]
    roi: Optional[ROI] = parse_roi_request(
        x1, y1, x2, y2, frame_width=width, frame_height=height, clamp=clamp
    )
    if roi is None:
        return image, None, (0, 0)

    cropped = image[roi.y1:roi.y2, roi.x1:roi.x2]
    return cropped, roi.as_xywh(), roi.offset


def roi_points_from_xywh(roi: Optional[list[int]]) -> Optional[list[int]]:
    """Convierte una ROI [x,y,w,h] a [x1,y1,x2,y2], o None si no hay ROI.

    No es una conversión de coordenadas (siguen siendo absolutas del frame), solo
    un cambio de representación de la misma caja, igual que hace hoy el backend.
    """
    if roi is None:
        return None
    x, y, w, h = roi
    return [x, y, x + w, y + h]
