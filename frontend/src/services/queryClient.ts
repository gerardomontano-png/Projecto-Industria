import { QueryClient } from '@tanstack/react-query';
import type { PersistedClient, Persister } from '@tanstack/react-query-persist-client';
import { API_URL } from '../config';
import { browserStorage } from './browserStorage';

const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export const queryKeys = {
  signal: ['signal'],
  cameras: ['cameras'],
  models: ['models'],
  lastInferenceEvent: ['lastInferenceEvent'],
} as const;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // gcTime >= maxAge del persister, si no la caché restaurada se descarta antes de usarse
      gcTime: CACHE_MAX_AGE_MS,
      staleTime: 30_000,
      retry: 1,
    },
  },
});

// La clave incluye la URL del servidor para no mezclar la caché de dos backends distintos.
const CACHE_KEY = `query-cache:${API_URL}`;

// Solo se guardan en disco los listados del backend. /signal es estado en vivo y el
// último evento de inferencia ya tiene su propio registro en IndexedDB.
const PERSISTED_KEYS: ReadonlySet<string> = new Set([queryKeys.cameras[0], queryKeys.models[0]]);

const persister: Persister = {
  persistClient: (client: PersistedClient) =>
    browserStorage.set(CACHE_KEY, client).catch(() => undefined),
  restoreClient: () => browserStorage.get<PersistedClient>(CACHE_KEY).catch(() => undefined),
  removeClient: () => browserStorage.remove(CACHE_KEY).catch(() => undefined),
};

export const persistOptions = {
  persister,
  maxAge: CACHE_MAX_AGE_MS,
  dehydrateOptions: {
    shouldDehydrateQuery: (query: { queryKey: readonly unknown[]; state: { status: string } }) =>
      query.state.status === 'success' && PERSISTED_KEYS.has(String(query.queryKey[0])),
  },
};
