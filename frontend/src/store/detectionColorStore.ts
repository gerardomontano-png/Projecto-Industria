import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface AccuracyLevel {
  label: string;
  color: string;
  threshold: number;
  operator: '>=' | '<=';
}

const DEFAULT_LEVELS: AccuracyLevel[] = [
  { label: 'Alta',  color: '#B4D678', threshold: 70, operator: '>=' },
  { label: 'Media', color: '#A3C2DF', threshold: 31, operator: '>=' },
  { label: 'Baja',  color: '#BD7066', threshold: 30, operator: '<=' },
];

interface DetectionColorState {
  levels: AccuracyLevel[];
  updateLevel: (index: number, patch: Partial<AccuracyLevel>) => void;
}

export const useDetectionColorStore = create<DetectionColorState>()(
  persist(
    (set) => ({
      levels: DEFAULT_LEVELS,
      updateLevel: (index, patch) =>
        set((state) => ({
          levels: state.levels.map((l, i) => (i === index ? { ...l, ...patch } : l)),
        })),
    }),
    {
      name: 'detection-color-store',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      migrate: migrateLevels,
    }
  )
);

/**
 * v0 guardaba Media ≥ 50, que junto con Baja ≤ 30 dejaba 31–49 % sin nivel.
 * Si el usuario no había cambiado ese umbral, se lleva al valor diseñado (31).
 */
export function migrateLevels(persisted: unknown, version: number): { levels: AccuracyLevel[] } {
  const state = persisted as { levels?: AccuracyLevel[] } | undefined;
  const levels = state?.levels ?? DEFAULT_LEVELS;
  if (version >= 1) return { levels };
  return {
    levels: levels.map((level) =>
      level.label === 'Media' && level.operator === '>=' && level.threshold === 50
        ? { ...level, threshold: 31 }
        : level
    ),
  };
}