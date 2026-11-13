# J07 — Proteger credenciales de fuentes de red

**Línea:** persistencia · **Orden:** J07 · **Depende de:** J01, J02, J03; política de datos sensibles aprobada

## Alcance

Evitar que credenciales contenidas en fuentes de red sean almacenadas o expuestas en respuestas, historial, métricas o documentación.

## El problema

Una cámara de red se configura con una URL que a menudo lleva usuario y contraseña, ya sea dentro de la autoridad de la URL (la parte `usuario:contraseña@` antes del host) o en parámetros de consulta (`?token=...`). Si esa URL se guarda tal cual o se imprime en un log, la contraseña queda expuesta a cualquiera que lea la base, una respuesta de la API o la consola del servidor.

La política aprobada de datos sensibles lo prohíbe: la base guarda solo la **fuente pública** (sin credenciales) y, por separado, el **nombre** de un secreto (`credential_ref`), nunca la credencial misma. Las tareas J01 y J03 ya aplicaban esta regla, pero cada una con su propia copia del código de detección. J07 la consolida en una sola salvaguarda central, verificada, y comprueba que ninguna de las cinco superficies que menciona el criterio filtre una credencial.

## La salvaguarda central

Todo el manejo de credenciales vive ahora en `app/services/credential_guard.py`, con dos tipos de operación según quién produce el dato.

**Rechazar** lo que el usuario controla y no debe traer credenciales. Si al registrar o actualizar una fuente llega una URL con credenciales, se rechaza con un error que le avisa. Así el usuario corrige y guarda la forma correcta.

| Función | Para qué |
|---|---|
| `contains_credentials(valor)` | ¿Este valor (texto, dict o lista) trae credenciales? |
| `reject_credentials(campo, valor)` | Devuelve el valor si está limpio; si no, lanza `CredentialLeakError` |
| `is_valid_credential_ref(valor)` | ¿Es el nombre de un secreto en mayúsculas, y no una credencial? |

**Enmascarar** lo que el sistema genera y podría arrastrar credenciales por accidente, como un mensaje de error del driver que incluyó la URL completa, o un log. Aquí no se puede fallar (el log debe salir), pero tampoco filtrar, así que se reemplaza la credencial por `***`.

| Función | Para qué |
|---|---|
| `redact_source(fuente)` | La fuente sin credenciales: `rtsp://***@host/s` |
| `redact(texto, *fuentes)` | Enmascara credenciales dentro de un texto libre |
| `redact_deep(estructura)` | Enmascara recursivamente en un dict o lista (para métricas) |

La distinción es deliberada: la entrada del usuario se **rechaza** para que la corrija; la salida del sistema se **enmascara** para no interrumpir el servicio ni filtrar.

## Qué se detecta

La salvaguarda reconoce credenciales en tres formas:

1. **Dentro de una URL:** la parte `usuario:contraseña@` o `usuario@` después del esquema.
2. **En parámetros de una URL:** `?password=...`, `?token=...`, `?secret=...`, y otros nombres sensibles (`api_key`, `auth`, `credential`, `bearer`, `signature`...).
3. **En campos de una estructura:** una clave de diccionario cuyo nombre indica una credencial (`password`, `token`, `Authorization`...) y que contiene texto no vacío, en cualquier nivel de anidamiento.

Para evitar falsos positivos, un campo con nombre sensible pero valor numérico o vacío (por ejemplo, `token_count: 5`) no se marca como credencial. La dirección y el puerto del host siempre se conservan, porque son útiles para diagnosticar.

## La referencia segura aprobada

Una cámara que necesita credenciales guarda en `credential_ref` únicamente el **nombre** de un secreto, por ejemplo el de una variable de entorno, en mayúsculas. La credencial real vive fuera de la base, en el gestor de secretos del despliegue. El modelo y el servicio rechazan cualquier `credential_ref` que parezca una credencial en vez de un nombre.

La respuesta pública de una fuente informa `has_credentials` (un booleano) y `credential_ref` (el nombre), nunca un secreto. Quien abre la cámara resuelve ese nombre contra el gestor de secretos; esa resolución es responsabilidad de la capa de cámaras, no de la persistencia.

## Las cinco superficies protegidas

El criterio exige que la credencial no aparezca en ninguna de estas superficies, y una prueba lo verifica sobre un escenario completo con una cámara IP y una contraseña de prueba:

| Superficie | Cómo se protege | Prueba |
|---|---|---|
| **Respuestas** | La vista pública solo lleva `has_credentials` y el nombre del secreto | `test_c1_la_respuesta_...`, `test_c3_escenario_completo_...` |
| **Historial (base)** | El modelo rechaza credenciales antes de guardar; se revisa la fila | `test_c2_el_modelo_...`, `test_c3_...` |
| **Métricas** | `redact_deep` limpia la estructura antes de reportarla | `test_c3_...` |
| **Logs** | `redact` enmascara el texto antes de registrarlo | `test_c3_...` (con `caplog`) |
| **Documentación** | Una prueba recorre los `.md` buscando URLs con credenciales reales | `test_docs_no_contienen_credenciales_de_ejemplo` |

La prueba de documentación encontró y corrigió dos ejemplos de documentos anteriores que usaban una URL con credenciales; ahora los ejemplos usan la forma enmascarada o placeholders en mayúsculas.

## Pruebas

```powershell
cd backend
python -m pytest tests/test_credential_guard.py -v
```

| Criterio | Pruebas |
|---|---|
| Las credenciales no aparecen en respuestas ni registros | `test_c1_*`, `test_c3_escenario_completo_...`, y las de detección y enmascarado |
| La persistencia almacena únicamente la referencia segura | `test_c2_*` (el modelo y el servicio rechazan credenciales; solo aceptan el nombre) |
| Las pruebas verifican serialización, errores, logs e historial | `test_c3_*` cubre las cuatro; `test_docs_*` cubre la documentación |

Se comprobó que las pruebas detectan los fallos reales: si la detección no reconoce las credenciales en una URL, si el enmascarado no las oculta, o si se acepta cualquier `credential_ref`, las pruebas correspondientes fallan.

## Cambios respecto a J01 y J03

J07 no cambia el comportamiento externo; consolida el interno:

- `app/db/models.py` y `app/services/source_schemas.py` dejan de tener su propia copia de las reglas y usan la salvaguarda central. El comportamiento es idéntico, verificado por las pruebas de J01 y J03 que siguen pasando sin cambios.
- Se corrigieron dos ejemplos en la documentación de J01 y J03 que mostraban una URL con credenciales.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j07_credenciales.py
```

Toma una URL de cámara IP con contraseña y token, y muestra: que la base la rechaza al intentar guardarla; cómo se registra correctamente (fuente pública + nombre del secreto); y que la misma contraseña, pasada por el enmascarado, no aparece en una respuesta, en una métrica simulada ni en una línea de log. Al final recorre todas las superficies y confirma que el secreto no está en ninguna. No necesita cámara, modelos ni red.

## Limitaciones y pendientes

- **Resolver el secreto** contra el gestor del despliegue al abrir la cámara es responsabilidad de la capa de cámaras, no de la persistencia.
- **El enmascarado cubre lo que produce la aplicación.** Si una librería externa (por ejemplo, OpenCV) escribe por su cuenta en la consola, esos mensajes están fuera del alcance; la recomendación es no pasarle URLs con credenciales.
- **Nombres de parámetro.** La lista de nombres sensibles es amplia pero no exhaustiva; `api_key`, `token`, `password` y similares están cubiertos. Un parámetro con un nombre inventado para una credencial no se detectaría, pero la forma `usuario:contraseña@` sí.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/services/credential_guard.py` | La salvaguarda central: detección, rechazo y enmascarado |
| `app/db/models.py` | Usa la salvaguarda central (antes tenía su copia) |
| `app/services/source_schemas.py` | Usa la salvaguarda central |
| `tests/test_credential_guard.py` | Pruebas de J07 |
| `scripts/demo_j07_credenciales.py` | Demostración reproducible |
| `docs/J07-proteccion-credenciales.md` | Este documento |
| `docs/J01-modelo-de-datos.md`, `docs/J03-administracion-fuentes.md` | Ejemplos corregidos |
