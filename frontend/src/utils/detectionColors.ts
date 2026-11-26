/**
 * Paleta fija de colores por clase de detección.
 * El color depende solo del classId, así una clase se ve igual en todos los frames,
 * cámaras y sesiones.
 */
import type { AccuracyLevel } from '../store/detectionColorStore';

export const DETECTION_PALETTE = [
  '#4E79A7', // azul
  '#F28E2B', // naranja
  '#E15759', // rojo
  '#76B7B2', // turquesa
  '#59A14F', // verde
  '#EDC948', // amarillo
  '#B07AA1', // morado
  '#FF9DA7', // rosa
  '#9C755F', // café
] as const;

/** Color para detecciones sin clase conocida (classId < 0) */
export const UNKNOWN_CLASS_COLOR = '#6b7280';

// Ángulo áureo: reparte los tonos lo más separados posible cuando hay más clases que colores
const GOLDEN_ANGLE = 137.508;

/** Devuelve siempre el mismo color para el mismo classId. */
export function colorForClass(classId: number): string {
  if (!Number.isInteger(classId) || classId < 0) return UNKNOWN_CLASS_COLOR;
  if (classId < DETECTION_PALETTE.length) return DETECTION_PALETTE[classId];

  const hue = Math.round((classId * GOLDEN_ANGLE) % 360);
  return `hsl(${hue}, 65%, 45%)`;
}

/** Color de texto legible (negro o blanco) sobre el color de la clase. */
export function labelTextColor(background: string): string {
  // Los hsl() generados usan luminosidad 45% → texto blanco
  if (!background.startsWith('#') || background.length !== 7) return '#fff';
  const r = parseInt(background.slice(1, 3), 16);
  const g = parseInt(background.slice(3, 5), 16);
  const b = parseInt(background.slice(5, 7), 16);
  // Luminancia percibida (ITU-R BT.601)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? '#1f2430' : '#fff';
}

/**
 * Devuelve el color según el nivel de confidence configurado por el usuario.
 *
 * Los niveles "≥" se evalúan del umbral más alto al más bajo. Todo lo que queda
 * por debajo del "≥" más bajo toma el color del nivel "≤" (el más bajo), así
 * ninguna detección se queda sin color aunque los umbrales dejen un hueco
 * (p. ej. Media ≥ 50 y Baja ≤ 30 dejaban 31–49 % en gris).
 */
export function colorForConfidence(
  confidence: number,
  levels: AccuracyLevel[]
): string {
  if (levels.length === 0) return UNKNOWN_CLASS_COLOR;
  const score = confidence * 100;

  const atLeast = levels
    .filter((level) => level.operator === '>=')
    .sort((a, b) => b.threshold - a.threshold);
  const match = atLeast.find((level) => score >= level.threshold);
  if (match) return match.color;

  const atMost = levels
    .filter((level) => level.operator === '<=')
    .sort((a, b) => a.threshold - b.threshold);
  const lowest = atMost.find((level) => score <= level.threshold) ?? atMost[atMost.length - 1];
  return (lowest ?? atLeast[atLeast.length - 1]).color;
}