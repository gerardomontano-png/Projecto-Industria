# J06 — Reducir eventos repetidos dentro de una ventana temporal

**Línea:** persistencia · **Orden:** J06 · **Depende de:** J04

## Alcance

Definir e implementar una política configurable para evitar registros redundantes de la misma detección.

## El problema

Una cámara industrial que observa una pieza quieta genera, frame tras frame, exactamente la misma detección. A 30 cuadros por segundo, una pieza que está diez segundos frente a la cámara produce 300 detecciones idénticas. Guardarlas todas llena la base de registros redundantes que no aportan nada: lo importante es "hubo una pieza en esta posición durante este rato", no cada uno de los 300 frames.

J06 define una política que decide cuándo una detección entrante es "la misma observación repetida" de otra reciente y debe omitirse, conservando siempre las detecciones distintas.

## Qué se considera un duplicado

Una detección es un duplicado de otra cuando se cumplen **dos** condiciones a la vez: están cerca en el tiempo (**ventana**) y son la misma observación (**equivalencia**).

### La ventana temporal

Dos detecciones solo se comparan si ocurren con menos de `window_seconds` de diferencia (2 segundos por defecto). Pasada la ventana, la misma pieza vuelve a registrarse, porque ya es una observación nueva y no un duplicado del frame anterior.

La ventana **se desliza**: cada vez que llega un duplicado, se refresca el tiempo de referencia. Así, una pieza que permanece quieta un minuto se deduplica durante todo ese minuto, no solo durante los primeros 2 segundos. En cuanto la pieza desaparece 2 segundos y vuelve, se registra de nuevo.

El borde es exclusivo: una detección a *exactamente* `window_seconds` de distancia ya está fuera de la ventana.

### El criterio de equivalencia

Dos detecciones son "la misma observación" cuando coinciden en:

| Parte | Por defecto | Configurable |
|---|---|---|
| **Cámara** | Debe ser la misma | Siempre (no se desactiva) |
| **Clase** (`class_id`) | Debe coincidir | `match_class` |
| **Etiqueta** (`label`) | Debe coincidir | `match_label` |
| **Posición** (solape de cajas) | IoU ≥ 0.5 | `iou_threshold` |

El solape de las cajas se mide con **IoU** (intersección sobre unión), la medida estándar de cuánto se superponen dos rectángulos: 0 si no se tocan, 1 si son idénticos. Dos detecciones de la misma pieza inmóvil tienen un IoU cercano a 1; si la pieza se mueve a otra parte del cuadro, el IoU baja y deja de ser un duplicado. El umbral `iou_threshold` decide cuánto solape basta; el borde es inclusivo (un IoU igual al umbral sí cuenta como duplicado).

Esto distingue bien los tres casos que importan:

- **Misma pieza quieta:** misma cámara, clase, etiqueta y caja solapada → duplicado, se omite.
- **Dos piezas distintas en el mismo frame:** distinta clase o cajas separadas → se guardan ambas.
- **La misma pieza que se mueve:** cajas que ya no se solapan → observaciones distintas, se guardan todas.

## Qué hace la política y qué no

La política **no borra nada**. Para cada detección entrante decide si es un duplicado reciente; el servicio de guardado usa esa decisión para **omitir** la detección redundante antes de insertarla. Las detecciones distintas siempre se guardan.

Un detalle importante: **el evento se guarda siempre**, aunque todas sus detecciones resulten duplicadas y el evento quede sin ninguna. Eso deja constancia de que el frame se procesó, que es distinto de no haberlo procesado. Así no se pierde la trazabilidad del proceso.

## Configuración

La política se crea con un `DedupConfig` y se pasa al servicio de guardado:

```python
from app.services.dedup_policy import DedupConfig, DedupPolicy
from app.services.detection_store import DetectionStoreService

politica = DedupPolicy(DedupConfig(window_seconds=2.0, iou_threshold=0.5))
svc = DetectionStoreService(db, dedup=politica)
```

| Parámetro | Por defecto | Significado |
|---|---|---|
| `enabled` | `True` | Si está en `False`, nada se deduplica: se guardan todas las detecciones |
| `window_seconds` | `2.0` | Tamaño de la ventana temporal |
| `iou_threshold` | `0.5` | Solape mínimo de cajas para considerarlas la misma posición |
| `match_class` | `True` | Si la clase debe coincidir |
| `match_label` | `True` | Si la etiqueta debe coincidir |

La configuración se valida al crear la política: una ventana no positiva o un umbral de IoU fuera de (0, 1] dan `DedupConfigError`. La función `describe_policy` genera una descripción en texto de la política activa, útil para logs y para registrar qué política se usó en una corrida.

Si no se pasa ninguna política al servicio, se usa una con los valores por defecto. Para desactivar la deduplicación por completo: `DedupPolicy(DedupConfig(enabled=False))`.

## Pruebas

```powershell
cd backend
python -m pytest tests/test_dedup.py -v
```

| Criterio | Pruebas |
|---|---|
| Reduce duplicados sin eliminar eventos distintos | `test_c1_*` (duplicado en la ventana, fuera de la ventana, ventana deslizante, detecciones distintas nunca se deduplican, cada cámara su cuenta; a través del guardado: omite la repetida pero guarda el evento, una pieza quieta se guarda una vez no cien, dos piezas distintas se guardan, misma caja distinta clase, pieza que se mueve, fuera de ventana se re-registra, sin política se guardan todas) |
| La ventana y el criterio de equivalencia están documentados y validados | `test_c2_*` (configuración inválida, descripción en texto) más esta documentación |
| Pruebas de detecciones repetidas, distintas y casos límite | las de IoU y equivalencia, y los casos límite: IoU justo en el umbral, tiempo justo en el borde de la ventana, `reset` |

Se comprobó que las pruebas detectan los fallos reales: si se ignora la ventana (todo sería duplicado), si la equivalencia ignora la clase (deduplicaría de más), o si el umbral de IoU usara `>` en vez de `>=` (el caso borde fallaría), las pruebas correspondientes fallan.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j06_dedup.py
```

Simula una línea donde una pieza permanece quieta frente a la cámara durante varios segundos (muchos frames idénticos), luego se mueve, y aparece una segunda pieza distinta. Muestra cuántas detecciones se habrían guardado sin la política y cuántas se guardan con ella, y demuestra que las piezas distintas y la misma pieza en otra posición se conservan. Al final imprime la descripción de la política. No necesita cámara, modelos ni red.

## Limitaciones y pendientes

- **La memoria de la política es por proceso.** Lleva en memoria las detecciones recientes por cámara; es ideal para deduplicar dentro de una corrida en curso. No deduplica contra lo que ya está en la base de corridas anteriores (ni haría falta: la ventana es de segundos).
- **El IoU compara cajas, no contenido.** Dos piezas idénticas que ocupan exactamente el mismo lugar en momentos distintos se tratan como la misma; para el conteo de una línea, eso suele ser lo correcto, pero conviene saberlo.
- **La ventana es de tiempo, no de número de frames.** Se basa en `captured_at`, así que funciona igual aunque el ritmo de captura varíe.
- **Sin integración con los WebSocket todavía.** J06 deja la política lista en el servicio de guardado; aplicarla en vivo al flujo de detección es trabajo de la tarea que conecte el guardado a los streams.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/services/dedup_policy.py` | La política: ventana, equivalencia, IoU, validación y descripción |
| `app/services/detection_store.py` | `save_event` aplica la política a cada detección |
| `tests/test_dedup.py` | Pruebas de J06 |
| `scripts/demo_j06_dedup.py` | Demostración reproducible |
| `docs/J06-deduplicacion.md` | Este documento |
