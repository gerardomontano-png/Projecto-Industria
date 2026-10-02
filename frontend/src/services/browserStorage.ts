import { createStore, del, get, set } from 'idb-keyval';

/** Única base IndexedDB de la app: caché de React Query, ROIs y último evento de inferencia. */
const store = createStore('camera-detection-ia', 'keyval');

export const browserStorage = {
  get: <T>(key: string): Promise<T | undefined> => get<T>(key, store),
  set: (key: string, value: unknown): Promise<void> => set(key, value, store),
  remove: (key: string): Promise<void> => del(key, store),
};
