import { describe, expect, it } from 'vitest';
import {
  groupDetectionsByClass,
  normalizeDetections,
  parseFrameMetadata,
  splitFrameMessage,
} from './frameMetadata';

/** Arma un mensaje del stream: [4 bytes uint32 BE = longitud JSON][JSON][JPEG]. */
function buildMessage(json: string, jpeg: number[]): ArrayBuffer {
  const jsonBytes = new TextEncoder().encode(json);
  const buffer = new ArrayBuffer(4 + jsonBytes.length + jpeg.length);
  new DataView(buffer).setUint32(0, jsonBytes.length, false);
  const bytes = new Uint8Array(buffer);
  bytes.set(jsonBytes, 4);
  bytes.set(jpeg, 4 + jsonBytes.length);
  return buffer;
}

describe('splitFrameMessage', () => {
  it('separa la metadata JSON del JPEG', () => {
    const { rawMeta, jpeg } = splitFrameMessage(buildMessage('{"fps":30}', [0xff, 0xd8, 0xff]));
    expect(rawMeta).toEqual({ fps: 30 });
    expect([...new Uint8Array(jpeg)]).toEqual([0xff, 0xd8, 0xff]);
  });

  it('entrega el JPEG aunque el JSON venga mal formado', () => {
    const { rawMeta, jpeg } = splitFrameMessage(buildMessage('{no-json', [1, 2, 3]));
    expect(rawMeta).toBeNull();
    expect([...new Uint8Array(jpeg)]).toEqual([1, 2, 3]);
  });

  it('trata como JPEG puro un buffer sin cabecera válida', () => {
    const pure = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]).buffer;
    const { rawMeta, jpeg } = splitFrameMessage(pure);
    expect(rawMeta).toBeNull();
    expect(jpeg).toBe(pure);
  });

  it('trata como JPEG puro un buffer de menos de 4 bytes', () => {
    const tiny = new Uint8Array([1, 2]).buffer;
    expect(splitFrameMessage(tiny)).toEqual({ rawMeta: null, jpeg: tiny });
  });
});

describe('normalizeDetections', () => {
  it('convierte el formato snake_case del backend', () => {
    const detections = normalizeDetections([
      { class_id: 2, class_name: 'cup', confidence: 0.56, bbox: { x1: 10, y1: 20, x2: 30, y2: 40 } },
    ]);
    expect(detections).toEqual([
      { classId: 2, className: 'cup', confidence: 0.56, bbox: { x1: 10, y1: 20, x2: 30, y2: 40 } },
    ]);
  });

  it('descarta las detecciones sin bbox válida', () => {
    const detections = normalizeDetections([
      { class_id: 1, confidence: 0.9 },
      { class_id: 1, confidence: 0.9, bbox: { x1: 0, y1: 0, x2: Number.NaN, y2: 10 } },
      null,
      'texto',
    ]);
    expect(detections).toEqual([]);
  });

  it('ordena las esquinas y limita la confianza a [0, 1]', () => {
    const [det] = normalizeDetections([
      { class_id: 0, confidence: 1.7, bbox: { x1: 30, y1: 40, x2: 10, y2: 20 } },
    ]);
    expect(det.bbox).toEqual({ x1: 10, y1: 20, x2: 30, y2: 40 });
    expect(det.confidence).toBe(1);
  });

  it('marca con classId -1 las detecciones sin clase', () => {
    const [det] = normalizeDetections([{ bbox: { x1: 0, y1: 0, x2: 1, y2: 1 } }]);
    expect(det.classId).toBe(-1);
    expect(det.confidence).toBe(0);
  });

  it('devuelve lista vacía si no recibe un arreglo', () => {
    expect(normalizeDetections(undefined)).toEqual([]);
    expect(normalizeDetections({})).toEqual([]);
  });
});

describe('groupDetectionsByClass', () => {
  it('agrupa por clase y ordena cada grupo por confianza descendente', () => {
    const bbox = { x1: 0, y1: 0, x2: 1, y2: 1 };
    const groups = groupDetectionsByClass([
      { classId: 5, className: 'cup', confidence: 0.4, bbox },
      { classId: 0, className: 'person', confidence: 0.9, bbox },
      { classId: 5, className: 'cup', confidence: 0.8, bbox },
    ]);

    expect(groups.map((g) => g.classId)).toEqual([0, 5]);
    expect(groups[1].className).toBe('cup');
    expect(groups[1].maxConfidence).toBe(0.8);
    expect(groups[1].detections.map((d) => d.confidence)).toEqual([0.8, 0.4]);
  });
});

describe('parseFrameMetadata', () => {
  it('convierte la metadata cruda de un frame', () => {
    const metadata = parseFrameMetadata(
      {
        camera_id: 0,
        fps: 29.5,
        timestamp: 1700000000.5,
        image_width: 640,
        image_height: 480,
        detections: [
          { class_id: 0, class_name: 'person', confidence: 0.9, bbox: { x1: 1, y1: 2, x2: 3, y2: 4 } },
        ],
      },
      7
    );

    expect(metadata.sequence).toBe(7);
    expect(metadata.cameraId).toBe('0');
    expect(metadata.fps).toBe(29.5);
    expect(metadata.capturedAt).toBe(1700000000500);
    expect(metadata.sourceSize).toEqual({ width: 640, height: 480 });
    expect(metadata.detections).toHaveLength(1);
    expect(metadata.byClass).toHaveLength(1);
  });

  it('devuelve un frame sin detecciones si no hay metadata', () => {
    const metadata = parseFrameMetadata(null, 3);
    expect(metadata.sequence).toBe(3);
    expect(metadata.cameraId).toBe('');
    expect(metadata.fps).toBe(0);
    expect(metadata.detections).toEqual([]);
    expect(metadata.byClass).toEqual([]);
    expect(metadata.sourceSize).toBeNull();
  });

  it('deja sourceSize en null si el backend no manda el tamaño de la imagen', () => {
    expect(parseFrameMetadata({ fps: 30 }, 0).sourceSize).toBeNull();
    expect(parseFrameMetadata({ image_width: 0, image_height: 480 }, 0).sourceSize).toBeNull();
  });
});
