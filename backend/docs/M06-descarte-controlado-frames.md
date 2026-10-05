# M06 — Último frame con descarte controlado

## Objetivo

Conservar únicamente la información necesaria del frame más reciente de la única cámara y aplicar descarte controlado, para que un consumidor lento (el cliente WebSocket o la inferencia) no haga crecer la memoria ni acumule retraso.

Depende de M04 y M05. Parte del desacople entre captura y comunicación (`docs/desacople-captura-websocket.md`), que introdujo el `FrameSlot`.

## Política

```
cámara ──read_frame()──▶ captura ──publish()──▶ FrameSlot (capacidad 1) ──next()──▶ emisor WebSocket
                                                       │                    └──next()──▶ inferencia
                                                       └─ al publicar, el frame anterior se reemplaza;
                                                          si nadie lo tomó, se cuenta como descartado
```

- **Un solo frame retenido.** `FrameSlot` guarda el frame más reciente y lo reemplaza en cada publicación. No hay cola.
- **Descarte controlado.** Un frame reemplazado antes de que algún consumidor lo tomara se descarta y se cuenta. Nunca se descarta un frame en uso: el consumidor que lo tomó conserva su referencia hasta terminar.
- **Siempre el más reciente.** `next(after_seq)` entrega el último frame con secuencia mayor a la última recibida. Un consumidor lento se salta los intermedios en lugar de recorrerlos.
- **Una sola copia.** La sesión ya no guarda su propio `last_frame`: ahora es una propiedad que lee del slot. El contrato de M01 (`session.last_frame`, `last_frame_ts`) se mantiene.

## Criterios de aceptación

| Criterio | Cómo se cumple | Pruebas |
|---|---|---|
| No existen colas sin límite | `FrameSlot` de capacidad 1. Los únicos historiales (`errors`, ventana de FPS) son `deque` con `maxlen`. Cada lectura de cámara, envío e inferencia espera a terminar antes de pedir la siguiente, así que nunca hay trabajo encolado | `test_no_existen_colas_sin_limite_en_el_backend` (análisis estático de `app/`), `test_slot_tiene_capacidad_de_un_frame` |
| La memoria no crece por frames atrasados | Solo sobreviven el frame del slot y los que tiene en uso cada consumidor | `test_slot_sin_consumidor_retiene_un_solo_frame`, `test_cliente_lento_no_acumula_frames_en_memoria`, `test_memoria_estable_con_cliente_lento_sostenido` |
| El único cliente recibe el frame más reciente | El emisor pide al slot el último frame y salta los intermedios | `test_cliente_lento_recibe_siempre_el_frame_mas_reciente`, `test_cliente_lento_recibe_frames_recientes_sin_retraso_acumulado` |
| Las métricas permiten observar capturados y descartados | Bloques `frame_buffer`, `delivery` e `inference` en `GET /cameras/session` | `test_metricas_permiten_observar_capturados_y_descartados`, `test_metricas_cuadran_frames_capturados_y_descartados`, `test_metricas_de_inferencia_cuentan_frames_analizados_y_saltados` |

Las pruebas de memoria se validaron también a la inversa: al introducir a propósito una lista sin límite en `FrameSlot.publish`, las tres fallan.

## Métricas en `GET /cameras/session`

```json
{
  "metrics":      {"frames_total": 144, "frames_dropped": 0, "fps_current": 24.1, "uptime_seconds": 6.0},
  "delivery":     {"frames_sent": 23, "frames_skipped": 120},
  "inference":    {"frames_inferred": 0, "frames_skipped": 0},
  "frame_buffer": {
    "capacity": 1,
    "frames_retained": 1,
    "frames_published": 144,
    "frames_consumed": 24,
    "frames_discarded": 119
  }
}
```

| Campo | Significado |
|---|---|
| `metrics.frames_total` | Frames capturados con éxito. Igual a `frame_buffer.frames_published` |
| `metrics.frames_dropped` | Lecturas fallidas del driver (`read_frame()` devolvió `None`). **No** son descartes por atraso; el nombre se conserva por el contrato de M01 |
| `frame_buffer.capacity` | Frames que puede retener el slot. Siempre 1 |
| `frame_buffer.frames_retained` | Frames retenidos ahora mismo: 0 o 1 |
| `frame_buffer.frames_consumed` | Frames que tomó al menos un consumidor |
| `frame_buffer.frames_discarded` | Frames reemplazados sin que ningún consumidor los tomara |
| `delivery.frames_sent` / `frames_skipped` | Frames enviados al cliente y frames que el emisor se saltó |
| `inference.frames_inferred` / `frames_skipped` | Frames analizados y no analizados. Los saltados incluyen los omitidos a propósito por `infer_every_n_frames` |

Balance que se cumple siempre: `frames_published = frames_consumed + frames_discarded + pendiente (0 o 1)`.

Los contadores son de la sesión: empiezan en cero en cada `acquire()`.

## Pruebas

Corren sin cámara física; la cámara y el WebSocket son dobles de prueba.

```powershell
cd backend
python -m pytest -v
```

Archivos de M06: `tests/test_m06_descarte_controlado.py` (criterios de aceptación) y las pruebas de descarte agregadas en `tests/test_frame_slot.py`, `tests/test_camera_session_manager.py` y `tests/test_stream_decoupling.py`.

## Demostración

```powershell
cd backend
python scripts/demo_m06_descarte.py
```

Ejecuta el código real de `/ws/stream` con frames de 640×480 durante 6 s por escenario e imprime cada segundo lo que expone `GET /cameras/session`, los frames vivos en memoria y la memoria asignada. Resultado de referencia (Windows, cámara simulada a ~24 FPS):

| Cliente | Capturados | Entregados | Descartados | Frames vivos | Memoria | Antigüedad al entregar |
|---|---|---|---|---|---|---|
| Rápido (0 ms) | 150 | 150 | 0 | 1–2 | ≤ 1.9 MB | ≤ 8 ms |
| Lento (250 ms) | 144 | 23 | 119 | 2 | 1.8–1.9 MB, plana | 34–50 ms |
| Muy lento (1000 ms) | 139 | 6 | 132 | 1–2 | ≤ 1.8 MB, plana | ≤ 78 ms |

Con una cola, el cliente lento habría acumulado ~121 frames (~112 MB) en 6 s y el retraso seguiría creciendo. Con descarte controlado, memoria y antigüedad se mantienen planas.

También se puede observar con el servidor real: inicia `uvicorn app.main:app`, conecta un cliente a `ws://127.0.0.1:8000/ws/stream?camera_id=0`, deja de leer del socket unos segundos y consulta `GET /cameras/session`: `frames_total` y `frame_buffer.frames_discarded` avanzan mientras `delivery.frames_sent` se detiene.

## Fuera del alcance

- **Navegador.** El frontend guarda hasta 3 frames recibidos y los dibuja del más viejo al más nuevo (`useCameraStream`), así que puede mostrar video hasta 2 frames atrasado respecto a lo que ya recibió. El backend cumple el criterio (entrega siempre el más reciente). Ajustar el dibujo del navegador para que muestre el último frame queda pendiente para después de integrar el PR #2, que modifica ese mismo código.
- **Búfer interno del driver.** OpenCV puede retener algunos frames en el búfer del dispositivo, fuera del control de la aplicación.
