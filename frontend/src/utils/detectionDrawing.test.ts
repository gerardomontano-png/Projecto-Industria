import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LocalizationDetection } from '../types';
import { colorForClass } from './detectionColors';
import { clearDetections, redrawDetections } from './detectionDrawing';

type Call = [method: string, ...args: number[]];

/** Canvas falso que registra las llamadas de dibujo en orden. */
function createCanvas() {
  const calls: Call[] = [];
  const strokeColors: string[] = [];
  const ctx = {
    font: '',
    lineWidth: 0,
    fillStyle: '',
    strokeStyle: '',
    setTransform: (...args: number[]) => calls.push(['setTransform', ...args]),
    clearRect: (...args: number[]) => calls.push(['clearRect', ...args]),
    strokeRect(...args: number[]) {
      calls.push(['strokeRect', ...args]);
      strokeColors.push(this.strokeStyle);
    },
    fillRect: (...args: number[]) => calls.push(['fillRect', ...args]),
    fillText: () => calls.push(['fillText']),
    measureText: () => ({ width: 40 }),
  };
  const canvas = { width: 0, height: 0, getContext: () => ctx };

  return {
    canvas: canvas as unknown as HTMLCanvasElement,
    calls,
    strokeColors,
    strokes: () => calls.filter(([method]) => method === 'strokeRect'),
  };
}

function detection(classId: number, x1: number, y1: number, x2: number, y2: number) {
  return { classId, className: `c${classId}`, confidence: 0.9, bbox: { x1, y1, x2, y2 } };
}

const FRAME = { width: 640, height: 480 };
const DISPLAY = { width: 1280, height: 720 };

describe('redrawDetections', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { devicePixelRatio: 1 });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('dibuja cada caja escalada con el letterbox y el color de su clase', () => {
    const { canvas, strokes, strokeColors } = createCanvas();
    const detections: LocalizationDetection[] = [
      detection(0, 100, 100, 200, 200),
      detection(2, 0, 0, 640, 480),
    ];

    redrawDetections(canvas, detections, FRAME, DISPLAY);

    expect(strokes()).toEqual([
      ['strokeRect', 310, 150, 150, 150],
      ['strokeRect', 160, 0, 960, 720],
    ]);
    expect(strokeColors).toEqual([colorForClass(0), colorForClass(2)]);
  });

  it('limpia la capa antes de dibujar las cajas del frame', () => {
    const { canvas, calls } = createCanvas();

    redrawDetections(canvas, [detection(0, 100, 100, 200, 200)], FRAME, DISPLAY);

    const clearIndex = calls.findIndex(([method]) => method === 'clearRect');
    const strokeIndex = calls.findIndex(([method]) => method === 'strokeRect');
    expect(calls[clearIndex]).toEqual(['clearRect', 0, 0, 1280, 720]);
    expect(clearIndex).toBeLessThan(strokeIndex);
  });

  it('no deja cajas del frame anterior cuando el siguiente no trae detecciones', () => {
    const { canvas, calls, strokes } = createCanvas();
    redrawDetections(canvas, [detection(0, 100, 100, 200, 200)], FRAME, DISPLAY);
    const callsAfterFirstFrame = calls.length;

    redrawDetections(canvas, [], FRAME, DISPLAY);

    const secondFrame = calls.slice(callsAfterFirstFrame).map(([method]) => method);
    expect(secondFrame).toContain('clearRect');
    expect(secondFrame).not.toContain('strokeRect');
    expect(strokes()).toHaveLength(1);
  });

  it('usa las cajas del frame que recibe, no las de frames anteriores', () => {
    const { canvas, calls, strokes } = createCanvas();
    redrawDetections(canvas, [detection(0, 100, 100, 200, 200)], FRAME, DISPLAY);
    const callsAfterFirstFrame = calls.length;

    redrawDetections(canvas, [detection(1, 0, 0, 100, 100)], FRAME, DISPLAY);

    const secondFrame = calls.slice(callsAfterFirstFrame);
    expect(secondFrame.filter(([method]) => method === 'strokeRect')).toEqual([
      ['strokeRect', 160, 0, 150, 150],
    ]);
    expect(strokes()).toHaveLength(2);
  });

  it('recalcula las cajas al cambiar el tamaño del canvas', () => {
    const { canvas, strokes } = createCanvas();

    redrawDetections(canvas, [detection(0, 100, 100, 200, 200)], FRAME, { width: 400, height: 600 });

    expect(canvas.width).toBe(400);
    expect(canvas.height).toBe(600);
    expect(strokes()).toEqual([['strokeRect', 62.5, 212.5, 62.5, 62.5]]);
  });

  it('ajusta el canvas al devicePixelRatio de la pantalla', () => {
    vi.stubGlobal('window', { devicePixelRatio: 2 });
    const { canvas, calls } = createCanvas();

    redrawDetections(canvas, [detection(0, 100, 100, 200, 200)], FRAME, DISPLAY);

    expect(canvas.width).toBe(2560);
    expect(canvas.height).toBe(1440);
    expect(calls).toContainEqual(['setTransform', 2, 0, 0, 2, 0, 0]);
  });

  it('no dibuja si el canvas aún no tiene tamaño', () => {
    const { canvas, calls } = createCanvas();
    redrawDetections(canvas, [detection(0, 100, 100, 200, 200)], FRAME, { width: 0, height: 0 });
    expect(calls).toEqual([]);
  });
});

describe('clearDetections', () => {
  it('borra toda la capa', () => {
    const { canvas, calls } = createCanvas();
    canvas.width = 800;
    canvas.height = 600;

    clearDetections(canvas);

    expect(calls).toEqual([
      ['setTransform', 1, 0, 0, 1, 0, 0],
      ['clearRect', 0, 0, 800, 600],
    ]);
  });
});
