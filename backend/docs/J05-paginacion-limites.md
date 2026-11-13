# J05 — Paginación, ordenamiento y límites de consulta

**Línea:** persistencia · **Orden:** J05 · **Depende de:** J03 y J04

## Alcance

Implementar paginación, ordenamiento, validación de filtros y límites máximos para consultas.

## Resumen

J04 trajo la consulta de eventos con filtros y una paginación básica por offset, con un tope de 1000. J05 la endurece para que ninguna consulta pueda devolver un conjunto ilimitado ni una página inestable, en cuatro frentes:

1. **Límites máximos** centralizados, con un tope real que no se puede rebasar.
2. **Ordenamiento** configurable, pero solo por campos de una lista blanca.
3. **Paginación estable** por cursor, además de la clásica por offset.
4. **Validación** completa de todos los parámetros de paginación y orden.

El núcleo vive en un módulo reutilizable, `query_pagination`, que no conoce el modelo de detección y podría servir a otras consultas.

## Límites máximos

| Constante | Valor | Qué significa |
|---|---|---|
| `DEFAULT_PAGE_SIZE` | 50 | Tamaño de página cuando el cliente no pide uno |
| `MAX_PAGE_SIZE` | 200 | Tope absoluto; nadie puede pedir más |

La regla clave: **un `limit` que supera el máximo se rechaza con un error, no se recorta en silencio**. Si un cliente pide un millón de resultados, recibe un `PaginationError` que le dice cuál es el tope, en vez de creer que recibió todo cuando solo recibió 200. Y si no pide `limit`, se aplica el valor por defecto, nunca "todos". Así, el criterio "las consultas no devuelven conjuntos ilimitados" se cumple por construcción.

La respuesta siempre informa el `total` de coincidencias, para que el cliente sepa cuántas páginas hay aunque cada una esté acotada.

## Ordenamiento

El cliente puede ordenar con `sort_by` y `sort_dir` (`asc` o `desc`). Pero solo se permiten los campos de una **lista blanca**:

| Campo | Orden |
|---|---|
| `captured_at` | Fecha de captura (por defecto, descendente) |
| `processed_at` | Fecha de procesamiento |
| `frame_seq` | Número de frame |
| `id` | Identificador |

Pedir ordenar por cualquier otro campo da un `PaginationError` que lista las opciones válidas. Esto evita dos problemas: que el cliente ordene por un campo arbitrario (incluso uno sensible), y que una consulta mal escrita ordene por algo inesperado en silencio. La dirección se valida igual: solo `asc` o `desc`.

Todo orden desempata por `id`, que es único. Sin ese desempate, dos eventos con la misma fecha podrían salir en orden distinto entre consultas, y la paginación se volvería inestable.

## Paginación: offset y cursor

Hay dos formas de paginar, y la respuesta soporta ambas.

**Por offset** (`limit` + `offset`): la clásica. Simple y suficiente para historiales de tamaño moderado. Su debilidad es que, si llegan eventos nuevos entre una página y otra, los resultados se desplazan y se pueden repetir o saltar filas.

**Por cursor** (`limit` + `cursor`): la estable. El `cursor` es una cadena opaca que codifica la posición exacta de la última fila entregada (su valor de orden y su id). La siguiente página pide "lo que viene después de esta posición", así que agregar filas nuevas no desplaza ni duplica lo ya visto. Es la opción recomendada para recorrer historiales grandes o que crecen mientras se leen.

La respuesta trae `next_cursor` cuando hay más resultados; el cliente lo pasa tal cual en la siguiente consulta. Un cursor corrupto o inventado se rechaza con un `PaginationError`, no produce resultados arbitrarios.

### Cómo se mantiene estable

El cursor compara por el campo de orden y desempata por id, respetando la dirección:

- Orden descendente: la siguiente página son las filas con valor **menor**, o con el mismo valor e id menor.
- Orden ascendente: al revés.

Una prueba inserta un evento nuevo entre dos páginas y confirma que no reaparece ninguno de los ya vistos; otra recorre un historial con todas las fechas iguales y comprueba que el cursor igual lo recorre completo, sin repetir ni saltar.

## Validación de filtros

Todos los parámetros se validan antes de tocar la base, con un error que señala el campo:

| Parámetro | Regla | Error |
|---|---|---|
| `limit` | Entero entre 1 y `MAX_PAGE_SIZE` | `PaginationError("limit")` |
| `offset` | Entero no negativo | `PaginationError("offset")` |
| `sort_by` | Campo de la lista blanca | `PaginationError("sort_by")` |
| `sort_dir` | `asc` o `desc` | `PaginationError("sort_dir")` |
| `cursor` | Cursor bien formado | `PaginationError("cursor")` |
| `min_confidence` | Entre 0 y 1 | `DetectionValidationError("min_confidence")` |
| `start` / `end` | Con zona horaria; fin posterior al inicio | `DetectionValidationError("period")` |

## Cambios respecto a J04

J05 modifica el contrato de consulta de J04 en dos puntos, y se actualizó la prueba de J04 que los comprobaba:

- El tope de página bajó de 1000 a `MAX_PAGE_SIZE` (200).
- Los errores de `limit` y `offset` ahora son `PaginationError` (antes `DetectionValidationError`), para distinguir los problemas de paginación de los de los filtros de contenido.

La forma de guardar eventos y los filtros de contenido de J04 no cambian.

## Pruebas

```powershell
cd backend
python -m pytest tests/test_pagination.py -v
```

| Criterio | Pruebas |
|---|---|
| Las páginas son estables y respetan los límites | `test_c1_*` (offset recorre todo sin repetir, cursor estable ante inserciones, cursor recorre el total una vez, orden por defecto, orden configurable, desempate estable) y las del módulo (`test_normalize_*`, `test_resolve_sort_*`, `test_cursor_*`) |
| Los filtros inválidos producen errores controlados | `test_c2_*` (campo de orden no permitido, dirección inválida, cursor corrupto, periodo invertido) |
| Las consultas no devuelven conjuntos ilimitados | `test_c3_*` (sin limit se aplica el defecto, un limit enorme se rechaza, el máximo es el tope real) |

Se comprobó que las pruebas detectan los fallos reales: si el tope máximo recortara en vez de rechazar, si `resolve_sort` aceptara cualquier campo, o si el cursor no desempatara por id, las pruebas correspondientes fallan.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j05_paginacion.py
```

Sobre una base en memoria con muchos eventos, recorre un historial por offset y por cursor mostrando que no hay repetidos, ordena por distintos campos, demuestra que el cursor sigue siendo estable cuando se insertan eventos a mitad del recorrido, y al final intenta varias consultas inválidas (limit enorme, orden por campo prohibido, cursor corrupto), mostrando cómo se rechaza cada una. No necesita cámara, modelos ni red.

## Limitaciones y pendientes

- **Sin endpoints todavía.** J05 refina el servicio; exponerlo como parámetros de consulta en `GET /events` es trabajo de la siguiente tarea.
- **El cursor codifica un solo campo de orden** más el id. Es suficiente para los campos de la lista blanca; un orden por varias columnas necesitaría extender el cursor.
- **El conteo total es exacto.** Para tablas enormes, un conteo exacto puede ser costoso; si llega a serlo, se puede cambiar por una estimación sin tocar la paginación.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/services/query_pagination.py` | Límites, ordenamiento, cursor y validación, reutilizables |
| `app/services/detection_schemas.py` | `EventQuery` y `EventPage` ampliados con cursor y orden |
| `app/services/detection_store.py` | `query` con orden configurable y paginación por cursor |
| `tests/test_pagination.py` | Pruebas de J05 |
| `tests/test_detection_store.py` | Ajuste de la prueba de límites al nuevo contrato |
| `scripts/demo_j05_paginacion.py` | Demostración reproducible |
| `docs/J05-paginacion-limites.md` | Este documento |
