/**
 * T-17 + T-19: Annotation Manager — Zustand 5 store for ROI management.
 * Supports undo/redo via past/future stacks.
 */
import { create } from 'zustand';
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware';
import { browserStorage } from '../services/browserStorage';

export interface StoredROI {
  id: string;
  cameraId: string;
  label: string;
  /** Normalized 0-1 */
  x: number;
  /** Normalized 0-1 */
  y: number;
  /** Normalized 0-1 */
  width: number;
  /** Normalized 0-1 */
  height: number;
  color: string;
  isEnabled: boolean;
}

const COLOR_PALETTE = ['#2f6fe4', '#e4832f', '#2fe46a', '#e42f6a', '#a02fe4', '#e4d12f'];

interface ROIState {
  rois: StoredROI[];
  selectedId: string | null;
  past: StoredROI[][];
  future: StoredROI[][];
}

interface ROIActions {
  selectRoi: (id: string | null) => void;
  addRoi: (roi: Omit<StoredROI, 'id' | 'color'>) => void;
  updateRoiDirect: (id: string, patch: Partial<StoredROI>) => void;
  pushHistory: () => void;
  deleteRoi: (id: string) => void;
  setLabel: (id: string, label: string) => void;
  setEnabled: (id: string, isEnabled: boolean) => void;
  undo: () => void;
  redo: () => void;
}

type ROIStore = ROIState & ROIActions;

function pickColor(rois: StoredROI[]): string {
  const used = rois.map((r) => r.color);
  return (
    COLOR_PALETTE.find((c) => !used.includes(c)) ??
    COLOR_PALETTE[rois.length % COLOR_PALETTE.length]
  );
}

function snapshot(state: ROIState): StoredROI[] {
  return state.rois.map((r) => ({ ...r }));
}

// Los ROIs se guardan en IndexedDB para sobrevivir a recargas y cortes de conexión.
// El historial de undo/redo y la selección son de la sesión actual y no se persisten.
const idbStorage: StateStorage = {
  getItem: async (name) => (await browserStorage.get<string>(name)) ?? null,
  setItem: (name, value) => browserStorage.set(name, value),
  removeItem: (name) => browserStorage.remove(name),
};

export const useROIStore = create<ROIStore>()(persist((set, get) => ({
  rois: [],
  selectedId: null,
  past: [],
  future: [],

  selectRoi(id) {
    set({ selectedId: id });
  },

  addRoi(roiData) {
    set((state) => {
      const newRoi: StoredROI = {
        ...roiData,
        id: crypto.randomUUID(),
        color: pickColor(state.rois),
      };
      return {
        past: [...state.past, snapshot(state)],
        future: [],
        rois: [...state.rois, newRoi],
        selectedId: newRoi.id,
      };
    });
  },

  updateRoiDirect(id, patch) {
    set((state) => ({
      rois: state.rois.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    }));
  },

  pushHistory() {
    // Snapshot current state into past so the NEXT undo goes back to it
    set((state) => ({
      past: [...state.past, snapshot(state)],
      future: [],
    }));
  },

  setLabel(id, label) {
    const trimmed = label.trim();
    if (!trimmed) return;
    set((state) => ({
      past: [...state.past, snapshot(state)],
      future: [],
      rois: state.rois.map((r) => (r.id === id ? { ...r, label: trimmed } : r)),
    }));
  },

  setEnabled(id, isEnabled) {
    set((state) => ({
      rois: state.rois.map((r) => (r.id === id ? { ...r, isEnabled } : r)),
    }));
  },

  undo() {
    const { past, rois } = get();
    if (past.length === 0) return;
    const previous = past[past.length - 1];
    set((state) => ({
      past: state.past.slice(0, -1),
      future: [snapshot(state), ...state.future],
      rois: previous,
      selectedId: null,
    }));
    // Suppress unused-variable lint on rois
    void rois;
  },

  redo() {
    const { future } = get();
    if (future.length === 0) return;
    const next = future[0];
    set((state) => ({
      past: [...state.past, snapshot(state)],
      future: state.future.slice(1),
      rois: next,
      selectedId: null,
    }));
  },

  deleteRoi(id) {
    set((state) => ({
      past: [...state.past, snapshot(state)],
      future: [],
      rois: state.rois.filter((r) => r.id !== id),
      selectedId: state.selectedId === id ? null : state.selectedId,
    }));

    // NOTA: el backend todavía no expone endpoints /rois (persistencia
    // pendiente). No llamar a roiApi aquí hasta que ese endpoint exista,
    // de lo contrario cada delete falla con 404 porque el ROI (creado con
    // crypto.randomUUID() en el cliente) nunca fue persistido en el backend.
  },
}), {
  name: 'roi-store',
  storage: createJSONStorage(() => idbStorage),
  partialize: (state) => ({ rois: state.rois }),
}));
