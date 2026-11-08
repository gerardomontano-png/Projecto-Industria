/**
 * T-027 / HU-08: filtro de resultados por umbral de confianza, en el cliente.
 *
 * El backend se consulta con un umbral bajo (CONF_FLOOR) y el filtro real se
 * aplica aquí al pintar: así mover el slider cambia lo mostrado al instante,
 * hacia arriba y hacia abajo, sin repetir la inferencia ni reabrir el stream.
 */
import type { InferenceResult } from '../types';

/** Umbral que se pide al backend: el mínimo del slider. */
export const CONF_FLOOR = 0.05;
/** Rango del control deslizante de confianza. */
export const CONF_MIN = CONF_FLOOR;
export const CONF_MAX = 0.95;

/** Conserva los elementos cuya confianza alcanza el umbral. */
export function filterByConfidence<T extends { confidence: number }>(
  items: readonly T[],
  threshold: number
): T[] {
  return items.filter((item) => item.confidence >= threshold);
}

/**
 * Aplica el umbral al resultado de cualquier tarea. Anomalías no se filtra:
 * su `score` mide diferencia contra la referencia, no confianza de un modelo.
 */
export function filterResultByConfidence(
  result: InferenceResult,
  threshold: number
): InferenceResult {
  switch (result.task) {
    case 'localization':
      return { ...result, detections: filterByConfidence(result.detections, threshold) };
    case 'classification':
      return { ...result, predictions: filterByConfidence(result.predictions, threshold) };
    case 'ocr':
      return { ...result, results: filterByConfidence(result.results, threshold) };
    default:
      return result;
  }
}
