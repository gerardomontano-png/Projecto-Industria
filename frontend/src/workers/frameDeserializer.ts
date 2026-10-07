/**
 * T-11: Web Worker — frame deserialization
 * Protocol: [4-byte uint32 BE JSON length][JSON][JPEG]
 * T-28: la metadata se parsea aquí; postMessage back { meta, jpeg } (StreamFrame)
 * transferring jpeg (zero-copy).
 */
import { decodeFrameMessage } from '../utils/frameMetadata';

self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  const buffer = event.data;
  if (!(buffer instanceof ArrayBuffer)) return;

  const frame = decodeFrameMessage(buffer);
  (self as unknown as Worker).postMessage(frame, [frame.jpeg]);
};
