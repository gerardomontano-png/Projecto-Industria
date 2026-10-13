import { describe, expect, it } from 'vitest';
import { bboxToCanvas, computeBBoxTransform, computeContainFit } from './bboxTransform';

const FRAME = { width: 640, height: 480 };

describe('computeContainFit', () => {
  it('deja barras laterales cuando el canvas es más ancho que el frame', () => {
    const fit = computeContainFit({ width: 1280, height: 720 }, FRAME);
    expect(fit).toEqual({ dx: 160, dy: 0, dw: 960, dh: 720, scale: 1.5 });
  });

  it('deja barras arriba y abajo cuando el canvas es más alto que el frame', () => {
    const fit = computeContainFit({ width: 400, height: 600 }, FRAME);
    expect(fit).toEqual({ dx: 0, dy: 150, dw: 400, dh: 300, scale: 0.625 });
  });

  it('no deja barras cuando el aspecto coincide', () => {
    const fit = computeContainFit({ width: 320, height: 240 }, FRAME);
    expect(fit).toEqual({ dx: 0, dy: 0, dw: 320, dh: 240, scale: 0.5 });
  });
});

describe('computeBBoxTransform', () => {
  const fit = computeContainFit({ width: 1280, height: 720 }, FRAME);

  it('usa la escala del letterbox si las bbox vienen en píxeles del frame', () => {
    expect(computeBBoxTransform(fit, FRAME)).toEqual({
      scaleX: 1.5,
      scaleY: 1.5,
      offsetX: 160,
      offsetY: 0,
    });
  });

  it('convierte desde el espacio del modelo cuando se indica sourceSize', () => {
    const t = computeBBoxTransform(fit, FRAME, { width: 320, height: 240 });
    expect(t.scaleX).toBe(3);
    expect(t.scaleY).toBe(3);
  });

  it('admite escala distinta por eje si el modelo estiró la imagen', () => {
    const t = computeBBoxTransform(fit, FRAME, { width: 640, height: 640 });
    expect(t.scaleX).toBe(1.5);
    expect(t.scaleY).toBeCloseTo(1.125);
  });

  it('ignora un sourceSize inválido y cae a píxeles del frame', () => {
    const t = computeBBoxTransform(fit, FRAME, { width: 0, height: 0 });
    expect(t.scaleX).toBe(1.5);
    expect(t.scaleY).toBe(1.5);
  });
});

describe('bboxToCanvas', () => {
  const fit = computeContainFit({ width: 1280, height: 720 }, FRAME);
  const transform = computeBBoxTransform(fit, FRAME);

  it('escala la caja y la desplaza por la barra del letterbox', () => {
    const rect = bboxToCanvas({ x1: 100, y1: 100, x2: 200, y2: 200 }, transform, fit);
    expect(rect).toEqual({ x: 310, y: 150, width: 150, height: 150 });
  });

  it('coloca la caja bajo la barra superior en un canvas vertical', () => {
    const tallFit = computeContainFit({ width: 400, height: 600 }, FRAME);
    const rect = bboxToCanvas(
      { x1: 0, y1: 0, x2: 640, y2: 480 },
      computeBBoxTransform(tallFit, FRAME),
      tallFit
    );
    expect(rect).toEqual({ x: 0, y: 150, width: 400, height: 300 });
  });

  it('recorta la caja al área visible de la imagen', () => {
    const rect = bboxToCanvas({ x1: -50, y1: -50, x2: 100, y2: 100 }, transform, fit);
    expect(rect).toEqual({ x: 160, y: 0, width: 150, height: 150 });
  });

  it('devuelve null si la caja queda fuera de la imagen', () => {
    expect(bboxToCanvas({ x1: 700, y1: 0, x2: 800, y2: 100 }, transform, fit)).toBeNull();
  });
});
