const DEFAULT_API_URL = 'http://127.0.0.1:8000';

/** URL base del backend. Se configura con VITE_API_URL (ver .env.example). */
export const API_URL: string = (import.meta.env.VITE_API_URL || DEFAULT_API_URL).replace(
  /\/+$/,
  ''
);

/** Misma base que API_URL pero para WebSocket (http → ws, https → wss). */
export const WS_URL: string = API_URL.replace(/^http/, 'ws');
