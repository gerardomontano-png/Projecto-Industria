/**
 * T-28: Parseo de la metadata JSON adjunta a cada frame del WebSocket.
 *
 * Contrato verificado contra encode_ws_message (backend/app/services/camera_service.py):
 *   mensaje binario = [4 bytes uint32 BE = longitud del JSON][JSON UTF-8][JPEG]
 *   JSON = { connected, camera_id, fps, timestamp, detections }
 *   detections[i] = { class_id, class_name, confidence, bbox: { x1, y1, x2, y2 } }
 *
 * Sin imports de valor (solo tipos) para poder usarse dentro del Web Worker.
 */
import type {
  BoundingBoxXYXY,
  LocalizationDetection,
  StreamFrame,
  StreamFrameMetadata,
} from '../types';

const HEADER_BYTES = 4;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function parseBBox(raw: unknown): BoundingBoxXYXY | null {
  if (!isRecord(raw)) return null;
  const { x1, y1, x2, y2 } = raw;
  if (!isFiniteNumber(x1) || !isFiniteNumber(y1) || !isFiniteNumber(x2) || !isFiniteNumber(y2)) {
    return null;
  }
  return { x1, y1, x2, y2 };
}

function parseDetection(raw: unknown): LocalizationDetection | null {
  if (!isRecord(raw)) return null;
  const bbox = parseBBox(raw.bbox);
  if (!bbox || !isFiniteNumber(raw.class_id) || !isFiniteNumber(raw.confidence)) return null;
  return {
    classId: raw.class_id,
    className: typeof raw.class_name === 'string' ? raw.class_name : undefined,
    confidence: raw.confidence,
    bbox,
  };
}

/** Las detecciones mal formadas se descartan en vez de rellenarse con valores por defecto. */
export function parseDetections(raw: unknown): LocalizationDetection[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(parseDetection).filter((d): d is LocalizationDetection => d !== null);
}

export function parseFrameMetadata(raw: unknown): StreamFrameMetadata | null {
  if (!isRecord(raw)) return null;
  return {
    cameraId: typeof raw.camera_id === 'string' ? raw.camera_id : '',
    fps: isFiniteNumber(raw.fps) ? raw.fps : 0,
    timestamp: isFiniteNumber(raw.timestamp) ? raw.timestamp : 0,
    detections: parseDetections(raw.detections),
  };
}

/** Separa un mensaje binario del stream en su metadata ya parseada y su JPEG. */
export function decodeFrameMessage(buffer: ArrayBuffer): StreamFrame {
  if (buffer.byteLength > HEADER_BYTES) {
    const jsonLen = new DataView(buffer).getUint32(0, false);
    const jpegOffset = HEADER_BYTES + jsonLen;
    if (jpegOffset < buffer.byteLength) {
      let meta: StreamFrameMetadata | null;
      try {
        const json = new TextDecoder().decode(new Uint8Array(buffer, HEADER_BYTES, jsonLen));
        meta = parseFrameMetadata(JSON.parse(json));
      } catch {
        meta = null;
      }
      return { meta, jpeg: buffer.slice(jpegOffset) };
    }
  }
  // Fallback: JPEG puro (sin cabecera JSON)
  return { meta: null, jpeg: buffer };
}

/** Nombre mostrable de la clase de una detección. */
export function detectionLabel(detection: LocalizationDetection): string {
  return detection.className ?? `clase ${detection.classId}`;
}

/** Agrupa las detecciones de un frame por clase, cada grupo ordenado por score descendente. */
export function groupDetectionsByClass(
  detections: LocalizationDetection[]
): Record<string, LocalizationDetection[]> {
  const groups: Record<string, LocalizationDetection[]> = {};
  for (const detection of detections) {
    (groups[detectionLabel(detection)] ??= []).push(detection);
  }
  for (const group of Object.values(groups)) {
    group.sort((a, b) => b.confidence - a.confidence);
  }
  return groups;
}
