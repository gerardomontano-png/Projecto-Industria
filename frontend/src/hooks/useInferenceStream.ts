/**
 * T-27: useInferenceStream — accepts options for conf/iou/inferEveryNFrames/roi/modelId.
 * Reconnects when URL params change.
 */
import { useState, useEffect, useRef } from 'react';
import type { LocalizationDetection } from '../types';
import { decodeFrameMessage } from '../utils/frameMetadata';

const WS_BASE = 'ws://127.0.0.1:8000/ws/inference-stream';

interface InferenceStreamOptions {
  modelId?: string;
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  roi?: { x1: number; y1: number; x2: number; y2: number } | null;
}

interface UseInferenceStreamResult {
  frameUrl: string | null;
  /** Detecciones YOLO incrustadas en el frame más reciente (vacío si aún no llegan) */
  detections: LocalizationDetection[];
  isConnected: boolean;
  error: string | null;
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
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [detections, setDetections] = useState<LocalizationDetection[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevUrlRef = useRef<string | null>(null);

  // Serialize URL as dependency so we reconnect when any option changes
  const wsUrl = buildWsUrl(cameraId, options);

  useEffect(() => {
    let ws: WebSocket | null = null;

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

        // Protocolo: [4 bytes uint32 BE = longitud JSON] [JSON con detecciones] [JPEG]
        const { meta, jpeg } = decodeFrameMessage(await event.data.arrayBuffer());

        if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
        const url = URL.createObjectURL(new Blob([jpeg], { type: 'image/jpeg' }));
        prevUrlRef.current = url;
        // Mismo batch de render: la imagen y sus detecciones cambian juntas
        setFrameUrl(url);
        setDetections(meta?.detections ?? []);
      };

      ws.onerror = () => setError('Error en la conexión WebSocket de inferencia');

      ws.onclose = () => setIsConnected(false);
    }, 0);

    return () => {
      clearTimeout(timer);
      if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = null;
      }
    };
  }, [wsUrl]);

  return { frameUrl, detections, isConnected, error };
}
