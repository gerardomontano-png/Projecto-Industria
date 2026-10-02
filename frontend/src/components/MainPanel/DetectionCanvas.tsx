// Capa de dibujo de las detecciones del modelo sobre el stream de video.
// Misma técnica que ROICanvas: un <canvas> absoluto encima del video. Aquí no hay
// interacción (pointer-events: none); el dibujo vive en utils/detectionDrawing y lo
// dispara useCameraStream en cada frame nuevo (y al redimensionar).
import type { Ref } from 'react';

interface DetectionCanvasProps {
  ref: Ref<HTMLCanvasElement>;
}

export function DetectionCanvas({ ref }: DetectionCanvasProps) {
  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      className="absolute inset-0 w-full h-full pointer-events-none"
    />
  );
}
