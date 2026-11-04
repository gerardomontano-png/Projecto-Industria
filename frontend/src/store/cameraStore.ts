/**
 * T-025: estado global de la cámara activa (Zustand 5).
 *
 * Solo guarda el id que eligió el usuario. La lista de cámaras es estado del
 * servidor y vive en React Query (hooks/useCameras.ts); no se duplica aquí.
 */
import { create } from 'zustand';

interface CameraState {
  /** null = el usuario aún no eligió: la UI usa la primera cámara que reporte el backend. */
  activeCameraId: string | null;
  setActiveCamera: (cameraId: string) => void;
}

export const useCameraStore = create<CameraState>((set) => ({
  activeCameraId: null,
  setActiveCamera: (cameraId) => set({ activeCameraId: cameraId }),
}));