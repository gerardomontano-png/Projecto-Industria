/**
 * Conversión de coordenadas de bounding boxes:
 *   espacio del modelo → píxeles del frame → canvas en pantalla (responsive + letterbox).
 *
 * El video se dibuja "contain": se escala uniformemente hasta caber en el canvas y
 * se centra, dejando barras (letterbox) si el aspecto no coincide. Las bbox deben
 * pasar por la misma transformación para coincidir con el objeto real.
 */
import type { BoundingBoxXYXY } from '../types';

export interface Size {
  width: number;
  height: number;
}

/** Rectángulo donde se dibujó la imagen dentro del canvas (ajuste "contain") */
export interface ImageFit {
  dx: number;
  dy: number;
  dw: number;
  dh: number;
  scale: number;
}

/** Transformación afín completa: canvasX = x * scaleX + offsetX */
export interface BBoxTransform {
  scaleX: number;
  scaleY: number;
  offsetX: number;
  offsetY: number;
}

export interface CanvasRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Letterbox: escala uniforme para que el frame quepa en el canvas, centrado. */
export function computeContainFit(display: Size, frame: Size): ImageFit {
  const scale = Math.min(display.width / frame.width, display.height / frame.height);
  const dw = frame.width * scale;
  const dh = frame.height * scale;
  return { dx: (display.width - dw) / 2, dy: (display.height - dh) / 2, dw, dh, scale };
}

/**
 * Factor de escala de coordenadas del modelo al canvas.
 * @param fit        Dónde quedó el frame dentro del canvas (computeContainFit)
 * @param frame      Tamaño real del frame (JPEG decodificado)
 * @param sourceSize Espacio en el que vienen las bbox. Si se omite, se asume que ya
 *                   vienen en píxeles del frame (lo que hace hoy el backend con YOLO).
 */
export function computeBBoxTransform(
  fit: ImageFit,
  frame: Size,
  sourceSize?: Size | null
): BBoxTransform {
  const source = sourceSize && sourceSize.width > 0 && sourceSize.height > 0 ? sourceSize : frame;
  // modelo → frame (puede no ser uniforme si el modelo estiró la imagen) → canvas
  return {
    scaleX: (frame.width / source.width) * fit.scale,
    scaleY: (frame.height / source.height) * fit.scale,
    offsetX: fit.dx,
    offsetY: fit.dy,
  };
}

/** Aplica la transformación a una bbox y la recorta al área visible de la imagen. */
export function bboxToCanvas(
  bbox: BoundingBoxXYXY,
  t: BBoxTransform,
  fit: ImageFit
): CanvasRect | null {
  const left = Math.max(fit.dx, bbox.x1 * t.scaleX + t.offsetX);
  const top = Math.max(fit.dy, bbox.y1 * t.scaleY + t.offsetY);
  const right = Math.min(fit.dx + fit.dw, bbox.x2 * t.scaleX + t.offsetX);
  const bottom = Math.min(fit.dy + fit.dh, bbox.y2 * t.scaleY + t.offsetY);

  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0) return null;
  return { x: left, y: top, width, height };
}
