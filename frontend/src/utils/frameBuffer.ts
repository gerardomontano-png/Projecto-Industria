/**
 * T-12: FrameBuffer — drop-oldest circular buffer (maxSize=3)
 */
import type { FrameMetadata } from '../types';

/** Un frame y SU metadata: viajan juntos para que overlay y datos no se desfasen */
export interface BufferedFrame {
  jpeg: ArrayBuffer;
  metadata: FrameMetadata;
}

export class FrameBuffer {
  private items: BufferedFrame[] = [];
  private readonly maxSize: number;

  constructor(maxSize = 3) {
    this.maxSize = maxSize;
  }

  push(item: BufferedFrame): void {
    if (this.items.length >= this.maxSize) {
      this.items.shift(); // drop oldest
    }
    this.items.push(item);
  }

  pop(): BufferedFrame | undefined {
    return this.items.shift();
  }

  clear(): void {
    this.items = [];
  }
}
