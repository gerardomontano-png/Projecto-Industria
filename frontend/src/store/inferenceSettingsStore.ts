/**
 * HU-08: sensibilidad de detección compartida entre vistas (Zustand 5).
 *
 * El umbral que fija el configurador vale igual en Monitor (stream en vivo) y
 * en Inferencia (imágenes y stream de prueba).
 */
import { create } from 'zustand';

/** Mismo valor por defecto que el backend (/ws/inference-stream, /inference/localization). */
export const DEFAULT_CONF_THRESHOLD = 0.25;

interface InferenceSettingsState {
  confThreshold: number;
  setConfThreshold: (value: number) => void;
}

export const useInferenceSettingsStore = create<InferenceSettingsState>((set) => ({
  confThreshold: DEFAULT_CONF_THRESHOLD,
  setConfThreshold: (value) => set({ confThreshold: Math.min(1, Math.max(0, value)) }),
}));
