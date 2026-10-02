/**
 * T-12: FrameBuffer (utils/frameBuffer) — drop-oldest circular buffer (maxSize=3)
 * T-13: Canvas rAF draw loop, ResizeObserver, Worker integration, bbox overlay
 * T-15: Exponential backoff reconnect
 * T-16: Watchdog for frozen streams
 */
import { useState, useEffect, useRef } from 'react';
import type { FrameMetadata } from '../types';
import type { FrameWorkerResult } from '../workers/frameDeserializer';
import { clearDetections, redrawDetections } from '../utils/detectionDrawing';
import { computeContainFit } from '../utils/bboxTransform';
import { FrameBuffer } from '../utils/frameBuffer';

const STREAM_WS_URL = 'ws://127.0.0.1:8000/ws/stream';
const INFERENCE_WS_URL = 'ws://127.0.0.1:8000/ws/inference-stream';

interface CameraStreamOptions {
  /** 'inference' abre /ws/inference-stream y cada frame trae sus detecciones */
  mode?: 'stream' | 'inference';
  modelId?: string;
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  roi?: { x1: number; y1: number; x2: number; y2: number } | null;
}

function buildWsUrl(cameraId: string, options: CameraStreamOptions): string {
  const params = new URLSearchParams();
  params.set('camera_id', cameraId);

  if (options.mode === 'inference') {
    if (options.modelId) params.set('model_id', options.modelId);
    if (options.conf !== undefined) params.set('conf', String(options.conf));
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

// ---------------------------------------------------------------------------
// Hook result
// ---------------------------------------------------------------------------
interface UseCameraStreamResult {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** Canvas de la capa de detecciones (se pasa a <DetectionCanvas />) */
  detectionCanvasRef: React.RefObject<HTMLCanvasElement | null>;
  isConnected: boolean;
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
  const [error, setError] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [displaySize, setDisplaySize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  const [frameMetadata, setFrameMetadata] = useState<FrameMetadata | null>(null);

  // Mutable refs that must not trigger re-renders
  const frameBuffer = useRef(new FrameBuffer(3));
  const backoffRef = useRef(500);
  const destroyedRef = useRef(false);
  const connectRef = useRef<() => void>(() => {});
  const wsRef = useRef<WebSocket | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef(0);
  const naturalSizeRef = useRef<{ width: number; height: number } | null>(null);
  const lastDrawnRef = useRef<DrawnFrame | null>(null);

  const wsUrl = buildWsUrl(cameraId, options);

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
  useEffect(() => {
    /** Olvida el último frame pintado y limpia la capa de detecciones */
    const resetDrawnFrame = () => {
      lastDrawnRef.current?.bitmap.close();
      lastDrawnRef.current = null;
      if (detectionCanvasRef.current) clearDetections(detectionCanvasRef.current);
    };

    destroyedRef.current = false;
    backoffRef.current = 500;
    lastFrameAtRef.current = 0;
    frameBuffer.current.clear();
    resetDrawnFrame();

    // Worker for frame deserialization
    const worker = new Worker(new URL('../workers/frameDeserializer.ts', import.meta.url), {
      type: 'module',
    });

    worker.onmessage = (event: MessageEvent<FrameWorkerResult>) => {
      const { metadata, jpeg } = event.data;
      lastFrameAtRef.current = Date.now();
      frameBuffer.current.push({ jpeg, metadata });
    };

    // T-15: connect function stored in ref to avoid stale closures
    function connect() {
      if (destroyedRef.current) return;

      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'blob';
      wsRef.current = ws;

      ws.onopen = () => {
        backoffRef.current = 500;
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
        worker.postMessage(buffer, [buffer]);
      };

      ws.onerror = () => setError('Error en la conexión WebSocket');

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        // Sin stream no se deben quedar cajas ni datos congelados del último frame
        resetDrawnFrame();
        setFrameMetadata(null);
        if (!destroyedRef.current) {
          // T-15: exponential backoff
          setTimeout(connectRef.current, backoffRef.current);
          backoffRef.current = Math.min(backoffRef.current * 2, 30_000);
        }
      };
    }

    connectRef.current = connect;

    // Start initial connection after a tick (StrictMode safety)
    const initTimer = setTimeout(connect, 0);

    // T-16: Watchdog — check for frozen stream every second
    const watchdogInterval = setInterval(() => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        if (lastFrameAtRef.current > 0 && Date.now() - lastFrameAtRef.current > 5000) {
          ws.close(); // triggers reconnect via onclose
        }
      }
    }, 1000);

    return () => {
      destroyedRef.current = true;
      clearTimeout(initTimer);
      clearInterval(watchdogInterval);
      worker.terminate();
      const ws = wsRef.current;
      if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
      wsRef.current = null;
    };
  }, [wsUrl]);

  return {
    canvasRef,
    detectionCanvasRef,
    isConnected,
    error,
    naturalSize,
    displaySize,
    frameMetadata,
  };
}
