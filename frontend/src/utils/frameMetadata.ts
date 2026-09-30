/**
 * Parseo de la metadata JSON que viaja adjunta a cada frame del WebSocket.
 * Formato de red: ver RawFrameMetadata en types/FrameTypes.tsx.
 * Funciones puras: se usan desde el Web Worker (frameDeserializer) y desde useInferenceStream.
 */
import type {
  DetectionClassGroup,
  FrameMetadata,
  LocalizationDetection,
  RawFrameMetadata,
} from '../types';

type RawDetection = NonNullable<RawFrameMetadata['detections']>[number] & {
  // Tolerancia por si algún emisor ya manda camelCase
  classId?: number;
  className?: string;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function classNameOf(det: LocalizationDetection): string {
  return det.className ?? `clase ${det.classId}`;
}

/**
 * Normaliza la lista de detecciones del backend (snake_case) al formato de React.
 * Descarta las entradas sin bbox válida en vez de inventar coordenadas.
 */
export function normalizeDetections(raw: unknown): LocalizationDetection[] {
  if (!Array.isArray(raw)) return [];

  const detections: LocalizationDetection[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const d = item as RawDetection;
    const bbox = d.bbox;
    if (
      !bbox ||
      !isFiniteNumber(bbox.x1) ||
      !isFiniteNumber(bbox.y1) ||
      !isFiniteNumber(bbox.x2) ||
      !isFiniteNumber(bbox.y2)
    ) {
      continue;
    }

    const classId = d.class_id ?? d.classId;
    const confidence = isFiniteNumber(d.confidence) ? d.confidence : 0;

    detections.push({
      classId: isFiniteNumber(classId) ? classId : -1,
      className: d.class_name ?? d.className,
      confidence: Math.min(1, Math.max(0, confidence)),
      // El backend manda x1,y1 = esquina superior izquierda, pero se normaliza por si acaso
      bbox: {
        x1: Math.min(bbox.x1, bbox.x2),
        y1: Math.min(bbox.y1, bbox.y2),
        x2: Math.max(bbox.x1, bbox.x2),
        y2: Math.max(bbox.y1, bbox.y2),
      },
    });
  }
  return detections;
}

/** Agrupa las detecciones por clase; cada grupo va ordenado por confianza descendente. */
export function groupDetectionsByClass(
  detections: LocalizationDetection[]
): DetectionClassGroup[] {
  const groups = new Map<number, DetectionClassGroup>();

  for (const det of detections) {
    let group = groups.get(det.classId);
    if (!group) {
      group = { classId: det.classId, className: classNameOf(det), detections: [], maxConfidence: 0 };
      groups.set(det.classId, group);
    }
    group.detections.push(det);
    group.maxConfidence = Math.max(group.maxConfidence, det.confidence);
  }

  for (const group of groups.values()) {
    group.detections.sort((a, b) => b.confidence - a.confidence);
  }
  return [...groups.values()].sort((a, b) => a.classId - b.classId);
}

/**
 * Convierte la metadata cruda de un frame en FrameMetadata.
 * Siempre devuelve un objeto (con lista vacía si no hay JSON o viene mal formado),
 * para que cada frame tenga su lista de detecciones.
 */
export function parseFrameMetadata(raw: unknown, sequence: number): FrameMetadata {
  const meta = raw && typeof raw === 'object' ? (raw as RawFrameMetadata) : {};
  const detections = normalizeDetections(meta.detections);

  return {
    sequence,
    cameraId: meta.camera_id !== undefined ? String(meta.camera_id) : '',
    fps: isFiniteNumber(meta.fps) ? meta.fps : 0,
    capturedAt: isFiniteNumber(meta.timestamp) ? Math.round(meta.timestamp * 1000) : Date.now(),
    detections,
    byClass: groupDetectionsByClass(detections),
    sourceSize:
      isFiniteNumber(meta.image_width) &&
      isFiniteNumber(meta.image_height) &&
      meta.image_width > 0 &&
      meta.image_height > 0
        ? { width: meta.image_width, height: meta.image_height }
        : null,
  };
}

/**
 * Separa un mensaje binario del WebSocket en metadata JSON + JPEG.
 * Protocolo: [4 bytes uint32 BE = longitud JSON][JSON][JPEG].
 * Si no trae cabecera válida se asume que el buffer es un JPEG puro.
 */
export function splitFrameMessage(buffer: ArrayBuffer): { rawMeta: unknown; jpeg: ArrayBuffer } {
  if (buffer.byteLength < 4) return { rawMeta: null, jpeg: buffer };

  const jsonLen = new DataView(buffer).getUint32(0, false);
  const jpegOffset = 4 + jsonLen;
  if (jpegOffset >= buffer.byteLength) return { rawMeta: null, jpeg: buffer };

  let rawMeta: unknown = null;
  try {
    rawMeta = JSON.parse(new TextDecoder().decode(buffer.slice(4, jpegOffset)));
  } catch {
    rawMeta = null;
  }
  return { rawMeta, jpeg: buffer.slice(jpegOffset) };
}
