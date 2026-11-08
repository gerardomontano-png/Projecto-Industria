import { useEffect, useState } from 'react';

/**
 * Devuelve `value` cuando lleva `delayMs` sin cambiar. El primer valor se
 * entrega de inmediato; solo los cambios posteriores esperan.
 *
 * Útil para valores que reabren recursos caros (p. ej. la URL de un WebSocket
 * que abre la cámara) y que cambian en ráfaga mientras se arrastra un control.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    if (Object.is(value, debounced)) return undefined;
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs, debounced]);

  return debounced;
}
