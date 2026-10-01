/**
 * T-27: useInferenceStream — accepts options for conf/iou/inferEveryNFrames/roi/modelId.
 * Reconnects when URL params change.
 */
import { useState, useEffect, useRef } from 'react';
import type { FrameMetadata, LocalizationDetection } from '../types';
import { parseFrameMetadata, splitFrameMessage } from '../utils/frameMetadata';
import { WS_URL } from '../config';
import {
  flushLiveInferenceFrame,
  recordLiveInferenceFrame,
  type LiveInferenceFrame,
} from '../services/lastInferenceEvent';

const WS_BASE = `${WS_URL}/ws/inference-stream`;
const NO_DETECTIONS: LocalizationDetection[] = [];

interface InferenceStreamOptions {
  modelId?: string;
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  roi?: { x1: number; y1: number; x2: number; y2: number } | null;
}

interface UseInferenceStreamResult {
  frameUrl: string | null;
  /** Metadata del frame en `frameUrl` (detecciones por clase, score, bbox) */
  frameMetadata: FrameMetadata | null;
  /** Detecciones YOLO incrustadas en el frame más reciente (vacío si aún no llegan) */
  detections: LocalizationDetection[];
  isConnected: boolean;
  error: string | null;
}

/** Frame y su metadata en un solo estado, para que nunca se rendericen desfasados */
interface CurrentFrame {
  url: string;
  metadata: FrameMetadata;
}

function buildWsUrl(cameraId: string, options: InferenceStreamOptions): string {
  const params = new URLSearchParams();
  params.set('camera_id', cameraId);
  if (options.modelId) params.set('model_id', options.modelId);
  if (options.conf !== undefined) params.set('conf', String(options.conf));
  if (options.iou !== undefined) params.set('iou', String(options.iou));
  if (options.inferEveryNFrames !== undefined)
    params.set('infer_every_n_frames', String(options.inferEveryNFrames));
  if (options.roi) {
    params.set('x1', String(options.roi.x1));
    params.set('y1', String(options.roi.y1));
    params.set('x2', String(options.roi.x2));
    params.set('y2', String(options.roi.y2));
  }
  return `${WS_BASE}?${params.toString()}`;
}

/**
 * Análogo a useCameraStream, pero contra /ws/inference-stream: el mismo framing
 * binario [uint32 BE len][JSON][JPEG], donde aquí el JSON trae las detecciones
 * YOLO en vez de venir vacío.
 */
export function useInferenceStream(
  cameraId: string,
  options: InferenceStreamOptions = {}
): UseInferenceStreamResult {
  const [current, setCurrent] = useState<CurrentFrame | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevUrlRef = useRef<string | null>(null);

  // Serialize URL as dependency so we reconnect when any option changes
  const wsUrl = buildWsUrl(cameraId, options);

  // Datos del análisis en vivo para el "último evento" guardado en IndexedDB.
  const liveEventMetaRef = useRef<Omit<LiveInferenceFrame, 'jpeg' | 'detections'> | null>(null);
  const { modelId, roi } = options;
  useEffect(() => {
    liveEventMetaRef.current = { cameraId, modelId: modelId ?? null, roi: roi ?? null };
  }, [cameraId, modelId, roi]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let sequence = 0;

    const timer = setTimeout(() => {
      ws = new WebSocket(wsUrl);
      ws.binaryType = 'blob';

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
      };

      ws.onmessage = async (event: MessageEvent) => {
        if (typeof event.data === 'string') {
          try {
            const handshake = JSON.parse(event.data) as {
              connected: boolean;
              description?: string;
            };
            if (!handshake.connected) {
              setError(handshake.description ?? 'No se pudo iniciar el stream de inferencia.');
            }
          } catch {
            // mensaje de texto no reconocido, se ignora
          }
          return;
        }

        if (!(event.data instanceof Blob)) return;

        const buffer = await event.data.arrayBuffer();
        const { rawMeta, jpeg } = splitFrameMessage(buffer);
        const metadata = parseFrameMetadata(rawMeta, sequence++);

        const liveMeta = liveEventMetaRef.current;
        if (liveMeta) {
          recordLiveInferenceFrame({ ...liveMeta, jpeg, detections: metadata.detections });
        }

        if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
        const url = URL.createObjectURL(new Blob([jpeg], { type: 'image/jpeg' }));
        prevUrlRef.current = url;
        setCurrent({ url, metadata });
      };

      ws.onerror = () => setError('Error en la conexión WebSocket de inferencia');

      ws.onclose = () => {
        setIsConnected(false);
        // Desconexión: asegura que el último frame analizado quede guardado.
        flushLiveInferenceFrame();
        setCurrent(null);
      };
    }, 0);

    return () => {
      clearTimeout(timer);
      flushLiveInferenceFrame();
      if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = null;
      }
    };
  }, [wsUrl]);

  return {
    frameUrl: current?.url ?? null,
    frameMetadata: current?.metadata ?? null,
    detections: current?.metadata.detections ?? NO_DETECTIONS,
    isConnected,
    error,
  };
}
