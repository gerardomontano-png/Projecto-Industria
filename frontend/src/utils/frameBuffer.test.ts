import { describe, expect, it } from 'vitest';
import { FrameBuffer, type BufferedFrame } from './frameBuffer';
import { parseFrameMetadata } from './frameMetadata';

/** Frame cuyo JPEG lleva su número de secuencia, para comprobar que viaja con su metadata. */
function frame(sequence: number): BufferedFrame {
  return {
    jpeg: new Uint8Array([sequence]).buffer,
    metadata: parseFrameMetadata({ fps: 30 }, sequence),
  };
}

function jpegId(item: BufferedFrame | undefined): number | undefined {
  return item ? new Uint8Array(item.jpeg)[0] : undefined;
}

describe('FrameBuffer', () => {
  it('entrega los frames en orden de llegada', () => {
    const buffer = new FrameBuffer(3);
    buffer.push(frame(0));
    buffer.push(frame(1));

    expect(buffer.pop()?.metadata.sequence).toBe(0);
    expect(buffer.pop()?.metadata.sequence).toBe(1);
    expect(buffer.pop()).toBeUndefined();
  });

  it('descarta el frame más antiguo cuando se llena', () => {
    const buffer = new FrameBuffer(3);
    for (let i = 0; i < 5; i++) buffer.push(frame(i));

    expect(buffer.pop()?.metadata.sequence).toBe(2);
    expect(buffer.pop()?.metadata.sequence).toBe(3);
    expect(buffer.pop()?.metadata.sequence).toBe(4);
    expect(buffer.pop()).toBeUndefined();
  });

  it('mantiene cada JPEG junto a la metadata de su mismo frame al descartar', () => {
    const buffer = new FrameBuffer(3);
    for (let i = 0; i < 10; i++) buffer.push(frame(i));

    for (let item = buffer.pop(); item; item = buffer.pop()) {
      expect(jpegId(item)).toBe(item.metadata.sequence);
    }
  });

  it('queda vacío después de clear', () => {
    const buffer = new FrameBuffer(3);
    buffer.push(frame(0));
    buffer.clear();
    expect(buffer.pop()).toBeUndefined();
  });
});
