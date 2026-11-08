/**
 * T-12: FrameBuffer (utils/frameBuffer) — drop-oldest circular buffer (maxSize=3)
 * T-13: Canvas rAF draw loop, ResizeObserver, Worker integration, bbox overlay
 * T-15: Exponential backoff reconnect
 * T-16: Watchdog for frozen streams
 *
 * HU-08: la URL del WebSocket se estabiliza con un debounce (mover un ROI o un
 * slider no debe abrir y cerrar la cámara en cada evento) y el ROI normalizado
 * se convierte a píxeles con la resolución REAL del frame recibido.
 */
import { useState, useEffect, useMemo, useRef } from 'react';
import type { FrameMetadata } from '../types';
import type { FrameWorkerResult } from '../workers/frameDeserializer';
import { clearDetections, redrawDetections } from '../utils/detectionDrawing';
import { computeContainFit } from '../utils/bboxTransform';
import { FrameBuffer } from '../utils/frameBuffer';
import { WS_URL } from '../config';
import { roiToBackendParams, type NormalizedROI } from '../utils/roiUtils';
import { useDebouncedValue } from './useDebouncedValue';
import {
  flushLiveInferenceFrame,
  recordLiveInferenceFrame,
  type LiveInferenceFrame,
} from '../services/lastInferenceEvent';

const STREAM_WS_URL = `${WS_URL}/ws/stream`;
const INFERENCE_WS_URL = `${WS_URL}/ws/inference-stream`;
/** T-015: tiempo máximo de caída continua antes de pasar a 'disconnected' y dejar de reintentar (2 min). */
const MAX_RECONNECT_MS = 120_000;
/** Espera tras el último cambio de parámetros antes de reconectar el WebSocket. */
const RECONNECT_DEBOUNCE_MS = 400;
/**
 * Errores que no se arreglan reintentando: la petición es inválida. Reintentar
 * solo abriría y cerraría la cámara en bucle (ver consola del backend).
 */
const NON_RETRYABLE_ERRORS = new Set(['INVALID_CAMERA_ID', 'INVALID_ROI', 'CAMERA_MISMATCH']);

interface CameraStreamOptions {
  /** 'inference' abre /ws/inference-stream y cada frame trae sus detecciones */
  mode?: 'stream' | 'inference';
  modelId?: string;
  /** Umbral de confianza; se aplica en vivo (mensaje por el socket), sin reconectar */
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  roi?: { x1: number; y1: number; x2: number; y2: number } | null;
  /**
   * ROI en coordenadas normalizadas (0–1). Se convierte a píxeles con el tamaño
   * real del frame que entrega la cámara; tiene prioridad sobre `roi`.
   */
  roiNormalized?: NormalizedROI | null;
}

function buildWsUrl(cameraId: string, options: CameraStreamOptions): string {
  const params = new URLSearchParams();
  params.set('camera_id', cameraId);

  if (options.mode === 'inference') {
    if (options.modelId) params.set('model_id', options.modelId);
    // conf NO va en la URL: cambiarlo reabriría la cámara. Se envía en vivo por el socket.
    if (options.iou !== undefined) params.set('iou', String(options.iou));
    if (options.inferEveryNFrames !== undefined) {
      params.set('infer_every_n_frames', String(options.inferEveryNFrames));
    }
    if (options.roi) {
      params.set('x1', String(options.roi.x1));
      params.set('y1', String(options.roi.y1));
      params.set('x2', String(options.roi.x2));
      params.set('y2', String(options.roi.y2));
    }
  }

  const base = options.mode === 'inference' ? INFERENCE_WS_URL : STREAM_WS_URL;
  return `${base}?${params.toString()}`;
}

/** HU-08: envía al backend el umbral vigente por el socket abierto, sin reconectar. */
function sendLiveConfig(ws: WebSocket, conf: number | undefined): void {
  if (conf === undefined || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'config', conf }));
}

// ---------------------------------------------------------------------------
// Canvas helpers
// ---------------------------------------------------------------------------

/** Último frame pintado: permite repintar video + cajas al redimensionar sin esperar otro frame */
interface DrawnFrame {
  bitmap: ImageBitmap;
  metadata: FrameMetadata;
}

/** Pinta el frame (letterbox) y su capa de detecciones con el tamaño actual del canvas. */
function paintFrame(
  canvas: HTMLCanvasElement,
  overlay: HTMLCanvasElement | null,
  { bitmap, metadata }: DrawnFrame
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const display = { width: canvas.width, height: canvas.height };
  const frameSize = { width: bitmap.width, height: bitmap.height };

  const fit = computeContainFit(display, frameSize);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, fit.dx, fit.dy, fit.dw, fit.dh);

  // Overlay del MISMO frame: se limpia y redibuja, sin acumular
  if (overlay) {
    redrawDetections(overlay, metadata.detections, frameSize, display, metadata.sourceSize);
  }
}

/** T-015: estado explícito de la conexión WebSocket, legible desde fuera del hook. */
export type WebSocketConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

// ---------------------------------------------------------------------------
// Hook result
// ---------------------------------------------------------------------------
interface UseCameraStreamResult {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** Canvas de la capa de detecciones (se pasa a <DetectionCanvas />) */
  detectionCanvasRef: React.RefObject<HTMLCanvasElement | null>;
  isConnected: boolean;
  connectionState: WebSocketConnectionState;
  error: string | null;
  naturalSize: { width: number; height: number } | null;
  displaySize: { width: number; height: number };
  /**
   * Metadata del frame que se está mostrando AHORA (detecciones por clase, score, bbox).
   * Se actualiza en el mismo paso en que se pinta el frame; null si no hay stream.
   */
  frameMetadata: FrameMetadata | null;
}

export function useCameraStream(
  cameraId: string,
  options: CameraStreamOptions = {}
): UseCameraStreamResult {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const detectionCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<WebSocketConnectionState>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [displaySize, setDisplaySize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  const [frameMetadata, setFrameMetadata] = useState<FrameMetadata | null>(null);

  // Mutable refs that must not trigger re-renders
  const frameBuffer = useRef(new FrameBuffer(3));
  /** Socket vigente; solo lo usa el efecto que envía la configuración en vivo */
  const wsRef = useRef<WebSocket | null>(null);
  /** Umbral a enviar al backend (solo en modo inferencia) */
  const liveConfRef = useRef<number | undefined>(undefined);
  const rafRef = useRef<number | null>(null);
  const naturalSizeRef = useRef<{ width: number; height: number } | null>(null);
  const lastDrawnRef = useRef<DrawnFrame | null>(null);

  // El ROI normalizado solo se puede pasar a píxeles cuando se conoce la
  // resolución real; hasta entonces se transmite sin ROI.
  const { roiNormalized } = options;
  const pixelRoi = useMemo(() => {
    if (roiNormalized === undefined) return options.roi ?? null;
    if (!roiNormalized || !naturalSize) return null;
    return roiToBackendParams(roiNormalized, naturalSize);
  }, [roiNormalized, naturalSize, options.roi]);
  const wsUrl = useDebouncedValue(
    buildWsUrl(cameraId, { ...options, roi: pixelRoi }),
    RECONNECT_DEBOUNCE_MS
  );

  // Datos del análisis en vivo para el "último evento". null fuera del modo inferencia:
  // el stream sin modelo no es un evento de inferencia y no debe pisar el guardado.
  const liveEventMetaRef = useRef<Omit<LiveInferenceFrame, 'jpeg' | 'detections'> | null>(null);
  const isInference = options.mode === 'inference';

  const { modelId } = options;
  useEffect(() => {
    liveEventMetaRef.current = isInference
      ? { cameraId, modelId: modelId ?? null, roi: pixelRoi }
      : null;
  }, [cameraId, isInference, modelId, pixelRoi]);

  // T-13: ResizeObserver — runs once, canvas is always in DOM
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        const w = Math.round(width);
        const h = Math.round(height);
        if (w > 0 && h > 0) {
          canvas.width = w;
          canvas.height = h;
          setDisplaySize({ width: w, height: h });
          // Cambiar el tamaño borra el canvas: se repinta el último frame con la nueva escala
          if (lastDrawnRef.current) {
            paintFrame(canvas, detectionCanvasRef.current, lastDrawnRef.current);
          }
        }
      }
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  // T-13: rAF draw loop — start once, keep running
  useEffect(() => {
    let cancelled = false;

    async function drawLoop() {
      if (cancelled) return;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');

      const frame = frameBuffer.current.pop();
      if (frame && canvas && ctx) {
        try {
          const blob = new Blob([frame.jpeg], { type: 'image/jpeg' });
          const bitmap = await createImageBitmap(blob);

          const size = naturalSizeRef.current;
          if (!size || size.width !== bitmap.width || size.height !== bitmap.height) {
            const ns = { width: bitmap.width, height: bitmap.height };
            naturalSizeRef.current = ns;
            setNaturalSize(ns);
          }

          const drawn: DrawnFrame = { bitmap, metadata: frame.metadata };
          paintFrame(canvas, detectionCanvasRef.current, drawn);
          lastDrawnRef.current?.bitmap.close();
          lastDrawnRef.current = drawn;
          setFrameMetadata(frame.metadata);
        } catch {
          // ignore decode errors
        }
      }

      rafRef.current = requestAnimationFrame(drawLoop);
    }

    rafRef.current = requestAnimationFrame(drawLoop);
    return () => {
      cancelled = true;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      lastDrawnRef.current?.bitmap.close();
      lastDrawnRef.current = null;
    };
  }, []);

  // T-11 + T-13 + T-15 + T-16: WebSocket + Worker + reconnect + watchdog
  //
  // Todo el estado de la conexión es LOCAL a esta ejecución del efecto. Antes
  // vivía en refs compartidas (destroyedRef, wsRef, connectRef): al cambiar la
  // URL (iniciar inspección, dibujar un ROI) el `onclose` tardío del socket
  // viejo veía destroyedRef=false del efecto nuevo, borraba wsRef y programaba
  // otra conexión. El socket que tenía la cámara quedaba huérfano, abierto y
  // entregando frames a un worker ya terminado: imagen congelada y CAMERA_BUSY
  // en bucle para todas las conexiones siguientes.
  useEffect(() => {
    /** Olvida el último frame pintado y limpia la capa de detecciones */
    const resetDrawnFrame = () => {
      lastDrawnRef.current?.bitmap.close();
      lastDrawnRef.current = null;
      if (detectionCanvasRef.current) clearDetections(detectionCanvasRef.current);
    };

    let disposed = false;
    let current: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = 500;
    /** T-015: instante en que empezó la caída actual; null si el stream está sano. */
    let downSince: number | null = null;
    let lastFrameAt = 0;

    frameBuffer.current.clear();
    resetDrawnFrame();

    // Worker for frame deserialization
    const worker = new Worker(new URL('../workers/frameDeserializer.ts', import.meta.url), {
      type: 'module',
    });

    worker.onmessage = (event: MessageEvent<FrameWorkerResult>) => {
      if (disposed) return;
      const { metadata, jpeg } = event.data;
      lastFrameAt = Date.now();
      downSince = null; // T-015: llegó un frame, la caída terminó
      backoff = 500; // la conexión funciona de verdad: se reinicia la espera
      frameBuffer.current.push({ jpeg, metadata });

      const liveMeta = liveEventMetaRef.current;
      if (liveMeta) {
        recordLiveInferenceFrame({ ...liveMeta, jpeg, detections: metadata.detections });
      }
    };

    function scheduleReconnect() {
      // T-015: cuenta la caída desde el primer cierre; si supera el tope, se rinde
      if (downSince === null) downSince = Date.now();
      if (Date.now() - downSince >= MAX_RECONNECT_MS) {
        setConnectionState('disconnected');
        return;
      }
      // T-15: exponential backoff. No se reinicia en `onopen`: un rechazo como
      // CAMERA_BUSY abre y cierra el socket, y reintentaría cada 500 ms sin fin.
      setConnectionState('reconnecting');
      retryTimer = setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 30_000);
    }

    function connect() {
      retryTimer = null;
      if (disposed) return;

      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'blob';
      current = ws;
      wsRef.current = ws;
      /** Código de error que el backend envió antes de cerrar (p. ej. INVALID_ROI) */
      let closeReason: string | null = null;

      ws.onopen = () => {
        if (disposed || ws !== current) return;
        // T-015: la conexión nueva aún no ha dado frames; sin esto el watchdog (T-16)
        // usa la hora del último frame de la conexión anterior y la cierra al instante.
        lastFrameAt = 0;
        frameBuffer.current.clear(); // T-015: volvió la conexión; descarta frames viejos del corte
        sendLiveConfig(ws, liveConfRef.current);
        setIsConnected(true);
        setConnectionState('connected');
        setError(null);
      };

      ws.onmessage = async (event: MessageEvent) => {
        if (disposed || ws !== current) return;
        if (typeof event.data === 'string') {
          try {
            const handshake = JSON.parse(event.data) as {
              connected: boolean;
              error?: string | null;
              description?: string;
            };
            if (!handshake.connected) {
              closeReason = handshake.error ?? null;
              setError(handshake.description ?? 'No se detectó ninguna cámara.');
            }
          } catch {
            // unknown text message, ignore
          }
          return;
        }
        if (!(event.data instanceof Blob)) return;

        // Transfer ArrayBuffer to worker (zero-copy)
        const buffer = await event.data.arrayBuffer();
        if (disposed) return;
        worker.postMessage(buffer, [buffer]);
      };

      ws.onerror = () => {
        if (!disposed && ws === current) setError('Error en la conexión WebSocket');
      };

      ws.onclose = () => {
        // Un socket que ya no es el vigente no toca el estado de nadie
        if (disposed || ws !== current) return;
        current = null;
        if (wsRef.current === ws) wsRef.current = null;
        setIsConnected(false);
        // Desconexión: asegura que el último frame analizado quede guardado.
        flushLiveInferenceFrame();
        // Sin stream no se deben quedar cajas ni datos congelados del último frame
        resetDrawnFrame();
        setFrameMetadata(null);
        // Petición inválida: reintentar no la arregla, solo reabriría la cámara en bucle
        if (closeReason && NON_RETRYABLE_ERRORS.has(closeReason)) {
          setConnectionState('disconnected');
          return;
        }
        scheduleReconnect();
      };
    }

    // Start initial connection after a tick (StrictMode safety)
    retryTimer = setTimeout(() => {
      setConnectionState('connecting');
      connect();
    }, 0);

    // T-16: Watchdog — check for frozen stream every second
    const watchdogInterval = setInterval(() => {
      const ws = current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        if (lastFrameAt > 0 && Date.now() - lastFrameAt > 5000) {
          ws.close(); // triggers reconnect via onclose
        }
      }
    }, 1000);

    return () => {
      disposed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      clearInterval(watchdogInterval);
      worker.terminate();
      flushLiveInferenceFrame();
      // Se cierra también si sigue en CONNECTING: si no, al abrir tomaría la cámara
      if (current && current.readyState < WebSocket.CLOSING) current.close();
      if (wsRef.current === current) wsRef.current = null;
      current = null;
    };
  }, [wsUrl]);

  // HU-08: el umbral de confianza viaja por el socket abierto, sin reconectar
  useEffect(() => {
    liveConfRef.current = isInference ? options.conf : undefined;
    const ws = wsRef.current;
    if (ws) sendLiveConfig(ws, liveConfRef.current);
  }, [isInference, options.conf]);

  return {
    canvasRef,
    detectionCanvasRef,
    isConnected,
    connectionState,
    error,
    naturalSize,
    displaySize,
    frameMetadata,
  };
}
