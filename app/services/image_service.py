from __future__ import annotations

import cv2
import numpy as np


class ImageInputError(ValueError):
    pass


def decode_image(data: bytes) -> np.ndarray:
    if not data:
        raise ImageInputError("La imagen está vacía.")
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageInputError("No se pudo decodificar la imagen.")
    return image


def resolve_roi(roi: str | None, image: np.ndarray) -> tuple[np.ndarray, list[int] | None, tuple[int, int]]:
    height, width = image.shape[:2]
    if roi is None or not roi.strip():
        return image, None, (0, 0)
    try:
        x, y, w, h = [int(value.strip()) for value in roi.split(",")]
    except Exception as exc:
        raise ImageInputError("ROI debe usar el formato x,y,width,height.") from exc
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ImageInputError("ROI contiene valores inválidos.")
    if x + w > width or y + h > height:
        raise ImageInputError("ROI está fuera de los límites de la imagen.")
    return image[y : y + h, x : x + w], [x, y, w, h], (x, y)


def map_bbox(box: list[float], offset: tuple[int, int]) -> dict[str, float]:
    ox, oy = offset
    return {
        "x1": float(box[0] + ox),
        "y1": float(box[1] + oy),
        "x2": float(box[2] + ox),
        "y2": float(box[3] + oy),
    }


def map_polygon(points: list[list[float]], offset: tuple[int, int]) -> list[list[float]]:
    ox, oy = offset
    return [[float(x + ox), float(y + oy)] for x, y in points]
