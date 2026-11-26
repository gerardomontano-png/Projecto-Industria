# [BACKEND][MVP] Contrato de coordenadas absolutas de ROI

**Depende de:** `image_service.py` (recorte), `stream_runner.py` (M07), los endpoints de inferencia.

## Alcance

Implementar en el backend el contrato de entrada para una región de interés (ROI) usando coordenadas absolutas `x1, y1, x2, y2` referidas al frame original.

## El problema que corrige

El backend ya recortaba por ROI, pero su validación tenía huecos justo en lo que pide este contrato. Al revisar el código existente se encontró:

- Una ROI con coordenadas **invertidas** (`x2 < x1`) se corregía en silencio con `min/max`, en vez de rechazarse. El criterio pide validar `x1 < x2`, no arreglarlo por detrás.
- No había forma de **limitar** una ROI que excede el frame: solo se rechazaba.
- En el stream de inferencia, una ROI inválida lanzaba una excepción que **cerraba el WebSocket con código 1011**. El criterio pide un error estructurado sin cerrar la conexión.
- Los valores eran enteros; el criterio habla de coordenadas **absolutas** y **finitas**, lo que incluye rechazar explícitamente NaN e infinito.

Esta tarea centraliza el contrato en un módulo, corrige esos cuatro puntos y lo valida.

## El contrato

Las coordenadas son **absolutas** y referidas al frame original: `(x1, y1)` es la esquina superior izquierda y `(x2, y2)` la inferior derecha. No hay conversión de coordenadas en ningún punto: lo que entra en coordenadas del frame sale en coordenadas del frame.

### Reglas

1. **Solo valores numéricos finitos.** Un valor que no es número, o que es `NaN` o infinito, se rechaza con `ROI_NOT_FINITE`. Un valor flotante válido se trunca al píxel entero (la unidad del frame).
2. **Orden y área positiva.** Debe cumplirse `x1 < x2` y `y1 < y2`. Una ROI invertida o de área nula se rechaza con `ROI_NOT_ORDERED`; **no se corrige en silencio**.
3. **Límites del frame.** Si la ROI excede las dimensiones del frame, por defecto se **rechaza** con `ROI_OUT_OF_BOUNDS`. Con el parámetro `clamp=true` se **limita** al borde del frame en vez de rechazarse. Si tras limitar queda sin área (estaba completamente fuera), se rechaza. Estas son las dos salidas controladas que pide el contrato.
4. **Ausencia de ROI = frame completo.** Si no se envía ningún valor, no hay ROI y se procesa el frame entero. Si se envían algunos pero no los cuatro, es un error `ROI_INCOMPLETE`.

### Decisión: rechazar por defecto, limitar bajo petición

El criterio dice "se limita **o** rechaza de forma controlada". Se eligió **rechazar por defecto** (comportamiento seguro y predecible: el cliente se entera de que su ROI no cabe) y ofrecer **limitar** como una opción explícita (`clamp=true`). Así se cubren las dos salidas, con la más estricta como predeterminada. Esta decisión se puede invertir con el líder técnico si el equipo prefiere que el ROI siempre se recorte.

## Códigos de error

Son parte del contrato: un cliente puede ramificar sobre ellos sin leer el texto.

| Código | Cuándo | HTTP (REST) |
|---|---|---|
| `ROI_NOT_FINITE` | Un valor no es un número finito | 400 |
| `ROI_INCOMPLETE` | Se dieron algunos valores pero no los cuatro | 400 |
| `ROI_NOT_ORDERED` | `x1 >= x2` o `y1 >= y2` (incluye área nula) | 400 |
| `ROI_OUT_OF_BOUNDS` | Excede el frame y no se pidió limitar | 400 |

## En REST

Los endpoints de inferencia reciben `x1, y1, x2, y2` como parámetros, y `clamp` opcional. Una ROI inválida produce un error 400 con una estructura estable:

```json
{"error": "ROI_NOT_ORDERED", "message": "La ROI debe cumplir x1 < x2 y y1 < y2 ...", "field": "roi"}
```

Una ROI válida se refleja en la respuesta en los campos `roi` (como `[x, y, w, h]`) y `roi_points` (como `[x1, y1, x2, y2]`), igual que hoy.

## En el WebSocket: sin cerrar la conexión

Este es el punto más delicado. En el stream de inferencia (`/ws/inference-stream`), la ROI se aplica a cada frame. Antes, un ROI inválido lanzaba una excepción que subía hasta el manejador genérico y cerraba el socket con 1011.

Ahora, `_inference_loop` captura el `ROIValidationError`: avisa al cliente con un mensaje estructurado (`{"connected": true, "error": "ROI_...", "description": ...}`) y **la transmisión de video continúa**. Mientras la ROI sea inválida, los frames se siguen enviando sin detecciones; en cuanto la ROI vuelva a ser válida, las detecciones se reanudan. El aviso se manda una vez por racha de fallo, para no inundar el socket, y vuelve a avisar si la ROI se recupera y falla de nuevo.

Así, un parámetro de ROI mal escrito nunca derriba la conexión del cliente.

## Fuera de alcance

- **Sin conversión de coordenadas.** Las coordenadas son absolutas de entrada a salida. Mapear entre resoluciones o sistemas de referencia no es parte de esta tarea.
- **Sin lógica de interfaz.** Todo es backend. El frontend decide cómo dibujar la ROI; aquí solo se valida la entrada.

## Pruebas

```powershell
cd backend
python -m pytest tests/test_roi_contract.py -v
```

| Criterio | Pruebas |
|---|---|
| Solo valores numéricos finitos | `test_no_finitos_se_rechazan`, `test_no_numericos_se_rechazan`, `test_enteros_y_flotantes_finitos_se_aceptan` |
| x1 < x2, y1 < y2 y área positiva | `test_orden_y_area_se_validan`, `test_la_roi_invertida_no_se_corrige_en_silencio` |
| Se limita o rechaza al exceder el frame | `test_fuera_del_frame_se_rechaza_por_defecto`, `test_fuera_del_frame_con_clamp_se_limita`, `test_clamp_de_una_roi_enteramente_fuera_se_rechaza` |
| ROI inválida: error estructurado sin cerrar el WebSocket | `test_ws_roi_invalida_no_cierra_la_conexion`, `test_ws_roi_vuelve_a_avisar_tras_recuperarse` |
| Ausencia de ROI = frame completo | `test_sin_roi_es_frame_completo`, `test_resolver_sin_roi_devuelve_frame_completo`, `test_rest_sin_roi_procesa_el_frame_completo` |
| Valores válidos, límites, invertidas y área nula | toda la sección del validador y del REST |

Se comprobó que las pruebas detectan los fallos reales: si la ROI invertida se corrigiera con min/max, si no se validaran los finitos, o si el WebSocket dejara propagar el error (cerrando la conexión), las pruebas correspondientes fallan.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_roi.py
```

Valida una ROI correcta, muestra el rechazo de cada caso inválido (no finito, invertida, área nula, fuera del frame, incompleta), demuestra el modo `clamp` y confirma que, en el stream, un ROI inválido avisa sin cerrar la conexión. No necesita cámara ni modelo.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/services/roi_contract.py` | El contrato: validación de finitos, orden, área y límites |
| `app/services/roi_resolver.py` | Puente entre el contrato y el recorte de la imagen |
| `app/api/routers/inference.py` | El endpoint usa el contrato; error 400 estructurado |
| `app/services/stream_runner.py` | ROI inválido en el stream avisa sin cerrar la conexión |
| `tests/test_roi_contract.py` | Pruebas del contrato |
| `scripts/demo_roi.py` | Demostración reproducible |
| `docs/BACKEND-contrato-roi.md` | Este documento |
