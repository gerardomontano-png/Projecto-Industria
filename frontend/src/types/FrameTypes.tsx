import type { ID, Timestamp } from './CommonTypes';
import type { Camera } from './CameraTypes';
import type { LocalizationDetection } from './InferenceTypes';

/* * Exporta la información de un frame capturado por una cámara industrial */
export type FrameEncoding = "jpeg" | "png" | "bmp" | "webp" | "raw";
export type FrameData = ArrayBuffer | Blob | string;


export interface Frame {
    readonly id: ID;
    readonly cameraId: Camera["id"];
    readonly capturedAt: Timestamp;
    readonly sequence: number;
    encoding: FrameEncoding;
    width: number;
    height: number;
    data: FrameData;
}

/**
 * Metadata JSON que el backend adjunta a cada frame del WebSocket
 * (/ws/stream y /ws/inference-stream), tal como llega por la red.
 * Protocolo: [4 bytes uint32 BE = longitud JSON][JSON UTF-8][JPEG]
 * Fuente: encode_ws_message() en backend/app/services/camera_service.py
 */
export interface RawFrameMetadata {
    connected?: boolean;
    camera_id?: string;
    fps?: number;
    /** Unix epoch en SEGUNDOS (time.time() de Python) */
    timestamp?: number;
    /**
     * OPCIONAL (el backend aún no lo manda): tamaño de la imagen en la que están
     * expresadas las bbox, si no son píxeles del frame enviado.
     */
    image_width?: number;
    image_height?: number;
    detections?: Array<{
        class_id?: number;
        class_name?: string;
        confidence?: number;
        bbox?: { x1: number; y1: number; x2: number; y2: number };
    }>;
}

/** Detecciones de una misma clase dentro de un frame */
export interface DetectionClassGroup {
    classId: number;
    className: string;
    /** Detecciones de esta clase, ordenadas por confianza descendente */
    detections: LocalizationDetection[];
    maxConfidence: number;
}

/** Metadata de UN frame ya parseada, lista para usarse en React */
export interface FrameMetadata {
    /** Contador local de frames recibidos en la conexión actual */
    readonly sequence: number;
    readonly cameraId: Camera["id"];
    readonly fps: number;
    /** Momento de captura en ms (compatible con Date) */
    readonly capturedAt: Timestamp;
    /** Todas las detecciones del frame (bbox en píxeles del frame original) */
    readonly detections: LocalizationDetection[];
    /** Las mismas detecciones agrupadas por clase */
    readonly byClass: DetectionClassGroup[];
    /** Espacio de coordenadas de las bbox; null = píxeles del frame (caso actual) */
    readonly sourceSize: { width: number; height: number } | null;
}
