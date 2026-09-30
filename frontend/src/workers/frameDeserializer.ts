/**
 * T-11: Web Worker — frame deserialization
 * Protocol: [4-byte uint32 BE JSON length][JSON][JPEG]
 * postMessage back { metadata, jpeg } transferring jpeg (zero-copy).
 * La metadata sale ya parseada (FrameMetadata) para no cargar el hilo principal.
 */
import type { FrameMetadata } from '../types';
import { parseFrameMetadata, splitFrameMessage } from '../utils/frameMetadata';

export interface FrameWorkerResult {
  metadata: FrameMetadata;
  jpeg: ArrayBuffer;
}

// Un worker por conexión: la secuencia arranca en 0 en cada stream nuevo
let sequence = 0;

self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  const buffer = event.data;
  if (!(buffer instanceof ArrayBuffer)) return;

  const { rawMeta, jpeg } = splitFrameMessage(buffer);
  const result: FrameWorkerResult = {
    metadata: parseFrameMetadata(rawMeta, sequence++),
    jpeg,
  };
  (self as unknown as Worker).postMessage(result, [jpeg]);
};
