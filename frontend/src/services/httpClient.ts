import axios from 'axios';
import { API_URL } from '../config';

/** Instancia axios compartida por todos los servicios que hablan con el backend. */
export const api = axios.create({
  baseURL: API_URL,
  timeout: 5000,
});

// T-24: Response interceptor — normaliza errores de red a mensajes legibles en español
api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      if (!error.response) {
        // Network error (no connection, CORS, timeout, etc.)
        return Promise.reject(
          new Error('No se pudo conectar con el servidor. Comprueba tu conexión.')
        );
      }
      // HTTP error with a response
      const status = error.response.status;
      if (status === 401) {
        return Promise.reject(new Error('No autorizado. Por favor inicia sesión de nuevo.'));
      }
      if (status === 403) {
        return Promise.reject(new Error('Acceso denegado.'));
      }
      if (status === 404) {
        return Promise.reject(new Error('El recurso solicitado no existe.'));
      }
      if (status >= 500) {
        return Promise.reject(new Error('Error interno del servidor. Inténtalo más tarde.'));
      }
    }
    return Promise.reject(error);
  }
);
