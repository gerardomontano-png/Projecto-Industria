import type {
  BoundingBoxXYXY,
  InferenceResult,
  LocalizationDetection,
  ModelTask,
  ROIRect,
} from '../types';
import { API_URL } from '../config';
import { browserStorage } from './browserStorage';
import { queryClient, queryKeys } from './queryClient';

/**
 * Último evento de inferencia (imagen subida o frame analizado en vivo).
 * Se guarda un único registro en IndexedDB: cada evento nuevo reemplaza al anterior.
 */
export interface LastInferenceEvent {
  id: string;
  /** 'image' = POST /inference/*, 'live' = frame de /ws/inference-stream */
  source: 'image' | 'live';
  serverUrl: string;
  createdAt: number;
  task: ModelTask;
  modelId: string | null;
  cameraId?: string;
  image: Blob;
  imageName: string;
  referenceImage?: Blob;
  referenceImageName?: string;
  /** ROI enviado al backend, en píxeles de la imagen. null = imagen completa. */
  roi: ROIRect | null;
  result: InferenceResult;
}

type NewInferenceEvent = Omit<LastInferenceEvent, 'id' | 'serverUrl' | 'createdAt'>;

const STORAGE_KEY = 'last-inference-event';

export async function loadLastInferenceEvent(): Promise<LastInferenceEvent | null> {
  try {
    return (await browserStorage.get<LastInferenceEvent>(STORAGE_KEY)) ?? null;
  } catch {
    return null;
  }
}

export async function recordInferenceEvent(input: NewInferenceEvent): Promise<void> {
  const event: LastInferenceEvent = {
    ...input,
    id: crypto.randomUUID(),
    serverUrl: API_URL,
    createdAt: Date.now(),
  };
  queryClient.setQueryData(queryKeys.lastInferenceEvent, event);
  try {
    await browserStorage.set(STORAGE_KEY, event);
  } catch {
    // Sin IndexedDB (p. ej. modo privado) el evento queda solo en memoria.
  }
}

// ---------------------------------------------------------------------------
// Análisis en vivo: llegan decenas de frames por segundo, así que solo se
// escribe a disco cada LIVE_SAVE_INTERVAL_MS y al cortarse/detenerse el stream.
// ---------------------------------------------------------------------------
const LIVE_SAVE_INTERVAL_MS = 2000;

export interface LiveInferenceFrame {
  cameraId: string;
  modelId: string | null;
  roi: BoundingBoxXYXY | null;
  jpeg: ArrayBuffer;
  detections: LocalizationDetection[];
}

let pendingLiveFrame: LiveInferenceFrame | null = null;
let lastLiveSaveAt = 0;

export function recordLiveInferenceFrame(frame: LiveInferenceFrame): void {
  pendingLiveFrame = frame;
  if (Date.now() - lastLiveSaveAt >= LIVE_SAVE_INTERVAL_MS) flushLiveInferenceFrame();
}

/** Guarda el último frame pendiente. Llamar al cerrar o perder el stream. */
export function flushLiveInferenceFrame(): void {
  const frame = pendingLiveFrame;
  if (!frame) return;
  pendingLiveFrame = null;
  lastLiveSaveAt = Date.now();

  const roi: ROIRect | null = frame.roi
    ? {
        x: frame.roi.x1,
        y: frame.roi.y1,
        width: frame.roi.x2 - frame.roi.x1,
        height: frame.roi.y2 - frame.roi.y1,
      }
    : null;

  void recordInferenceEvent({
    source: 'live',
    task: 'localization',
    modelId: frame.modelId,
    cameraId: frame.cameraId,
    image: new Blob([frame.jpeg], { type: 'image/jpeg' }),
    imageName: `camara-${frame.cameraId}.jpg`,
    roi,
    result: {
      task: 'localization',
      modelId: frame.modelId ?? '',
      roi: roi ? [roi.x, roi.y, roi.width, roi.height] : null,
      detections: frame.detections,
    },
  });
}
