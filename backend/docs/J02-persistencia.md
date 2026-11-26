# J02 — Configuración, sesiones, repositorios y migración inicial

**Línea:** persistencia · **Orden:** J02 · **Depende de:** J01 (modelo de datos)

## Alcance

Implementar configuración de base de datos, gestión de sesiones, repositorios y migraciones iniciales.

## Resumen

J01 definió *qué* se guarda. J02 construye *cómo* se guarda y se consulta, en cuatro piezas:

1. **Configuración** (`app/db/config.py`): la conexión y el pool se leen del entorno, con SQLite por defecto para desarrollo y PostgreSQL en producción, sin cambiar código.
2. **Sesiones** (`app/db/session.py`): el motor único del proceso y un contexto transaccional que abre, confirma, revierte y cierra cada unidad de trabajo.
3. **Repositorios** (`app/db/repositories/`): las consultas de cada entidad reunidas en un lugar, en vez de SQL disperso.
4. **Migración inicial** (`alembic/`): crea el esquema completo desde una base vacía, y puede deshacerlo.

## Configuración

Los valores se toman de variables de entorno con el prefijo `DB_`, o de un archivo `.env`. Hay un `.env.example` como plantilla.

| Variable | Por defecto | Para qué |
|---|---|---|
| `DB_URL` | `sqlite+pysqlite:///./data/vision.db` | Conexión. En producción, PostgreSQL |
| `DB_ECHO` | `false` | Imprime el SQL ejecutado (solo para depurar) |
| `DB_POOL_SIZE` | `5` | Conexiones del pool (se ignora en SQLite) |
| `DB_MAX_OVERFLOW` | `10` | Conexiones extra bajo demanda |
| `DB_POOL_TIMEOUT` | `30` | Segundos de espera por una conexión |
| `DB_POOL_RECYCLE` | `1800` | Segundos antes de renovar una conexión |

Dos detalles de seguridad y portabilidad:

- `safe_url` devuelve la URL con la contraseña enmascarada, para que ningún log la exponga.
- `engine_kwargs()` aplica los parámetros de pool solo fuera de SQLite, porque SQLite no usa ese pool. En SQLite permite compartir la conexión entre hilos, ya que el servidor lee la cámara en hilos aparte.

## Sesiones

El motor (el pool de conexiones) se crea una sola vez por proceso con `init_engine`. Las unidades de trabajo usan `session_scope`:

```python
from app.db.session import session_scope
from app.db.repositories import CameraRepository

with session_scope() as db:
    repo = CameraRepository(db)
    repo.add(nueva_camara)
# al salir sin error, se hizo commit; si hubo excepción, rollback
```

El contexto garantiza tres cosas:

- **Confirma** (`commit`) si el bloque terminó sin excepción.
- **Revierte** (`rollback`) si hubo una excepción, y la vuelve a lanzar.
- **Cierra** la sesión siempre.

Para FastAPI, `get_session` es la dependencia equivalente: entrega una sesión y la confirma si la petición terminó bien o la revierte si falló.

### La regla de los commits

Quien abre la sesión decide cuándo se confirma; los repositorios nunca hacen commit. Esto permite que varias operaciones formen una sola unidad atómica: si cualquiera falla, se revierte todo. Una prueba lo verifica guardando una cámara válida y otra inválida en el mismo bloque, y comprobando que ninguna de las dos queda.

## Repositorios

Cada repositorio hereda de `Repository`, que trae `add`, `get`, `list`, `count` y `delete`. Encima, cada uno agrega las consultas propias de su entidad:

| Repositorio | Consultas propias |
|---|---|
| `CameraRepository` | `get_by_name`, `get_by_source`, `list_by_status`, `list_active` |
| `ProcessingRunRepository` | `history_for_camera` (reciente primero), `list_active`, `list_by_status` |
| `DetectionEventRepository` | `list_for_run`, `list_for_camera_between` (por rango de fechas) |
| `DetectionRepository` | `list_for_event`, `count_by_label_for_run` |

Las consultas se apoyan en los índices de J01: `history_for_camera` usa `ix_processing_runs_camera_id_created_at` y `list_for_camera_between` usa `ix_detection_events_camera_id_captured_at`.

El `add` hace `flush` por defecto: envía el INSERT a la base para que las restricciones se verifiquen de inmediato y la fila reciba sus valores por defecto, pero la transacción sigue abierta hasta el commit de quien controla la sesión.

## Migración inicial

La migración `0001_modelo_inicial` crea las cuatro tablas, sus restricciones y sus seis índices desde una base vacía, y su `downgrade` los elimina.

```powershell
cd backend
python -m alembic upgrade head      # crea el esquema
python -m alembic current           # muestra la versión aplicada
python -m alembic downgrade base    # lo deshace
```

Decisiones de la configuración de Alembic:

- **La URL no se escribe en `alembic.ini`.** `env.py` la toma de la configuración de la aplicación (la variable `DB_URL`), para tener una sola fuente de verdad y no versionar credenciales.
- **`render_as_batch` en SQLite.** SQLite no soporta `ALTER TABLE` completo; el modo batch recrea la tabla cuando una migración futura lo necesite. En PostgreSQL no se usa.
- **`compare_type`** detecta cambios de tipo de columna al autogenerar migraciones futuras.
- **La migración se generó automáticamente** desde el modelo de J01 (`alembic revision --autogenerate`) y luego se revisó: el `UTCDateTime` de J01 define su propio `__repr__` para que la migración lo use sin un prefijo de módulo roto.

La migración y el modelo no pueden divergir: una prueba aplica la migración sobre una base limpia y compara tabla por tabla y columna por columna contra `Base.metadata`.

## Pruebas

Cada prueba usa una base SQLite temporal en disco, nueva por caso. Las migraciones necesitan una conexión real a archivo, no `:memory:`, porque cada conexión en memoria vería una base distinta.

```powershell
cd backend
python -m pytest tests/test_persistence.py -v
```

| Criterio | Pruebas |
|---|---|
| Las migraciones crean la base desde un entorno limpio | `test_c1_la_migracion_crea_todo_el_esquema`, `test_c1_el_esquema_migrado_coincide_con_el_modelo`, `test_c1_upgrade_y_downgrade_son_reversibles`, `test_c1_la_migracion_aplica_las_restricciones` |
| Las sesiones se abren, confirman, revierten y cierran | `test_c2_session_scope_confirma_al_terminar_bien`, `test_c2_session_scope_revierte_ante_un_error`, `test_c2_rollback_deja_la_sesion_reutilizable`, `test_c2_una_violacion_de_integridad_revierte_toda_la_unidad`, `test_c2_la_dependencia_de_fastapi_confirma_al_agotar_el_generador`, `test_c2_la_dependencia_revierte_si_la_peticion_falla`, `test_c2_init_engine_es_idempotente_y_force_reinicia` |
| Las pruebas de repositorio son reproducibles | `test_c3_*` (cadena completa, cámaras, historial de corridas, corridas activas, conteo por etiqueta, rango de fechas) |

Se comprobó que las pruebas detectan los fallos reales: si se quita el rollback de `session_scope`, falla `test_c2_rollback_deja_la_sesion_reutilizable`; si se apagan las llaves foráneas, falla `test_c1_la_migracion_aplica_las_restricciones`.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j02_persistencia.py
```

Crea una base SQLite temporal, aplica la migración inicial, guarda una cámara con una corrida y sus detecciones usando los repositorios, consulta el historial, demuestra que un error revierte toda la unidad de trabajo y, al final, deshace la migración. No necesita cámara, modelos ni red; borra su base temporal al terminar.

## Limitaciones y pendientes

- **Una sola migración.** Hay solo la inicial. Las siguientes se generan con `alembic revision --autogenerate` y se revisan antes de confirmar; el modo batch ya está configurado para SQLite.
- **Sin pool asíncrono.** Las sesiones son síncronas. Las corridas de los WebSocket deben guardar fuera del event loop (por ejemplo, con `run_in_executor`) o adoptarse SQLAlchemy async en una tarea posterior.
- **La integración con la API es de otra tarea.** J02 deja listas las sesiones y los repositorios; conectarlos a los endpoints y a los WebSocket corresponde a las siguientes tareas de la línea.
- **`.env` no se versiona.** El `.env.example` es la plantilla; cada quien crea su `.env`, que queda fuera de git.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/db/config.py` | Configuración leída del entorno, con URL segura |
| `app/db/session.py` | Motor, `session_scope`, dependencia de FastAPI |
| `app/db/repositories/base.py` | Repositorio genérico |
| `app/db/repositories/camera.py`, `run.py`, `detection.py` | Repositorios por entidad |
| `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` | Configuración de migraciones |
| `alembic/versions/0001_modelo_inicial.py` | Migración inicial |
| `.env.example` | Plantilla de configuración |
| `tests/test_persistence.py` | Pruebas de J02 |
| `scripts/demo_j02_persistencia.py` | Demostración reproducible |
| `app/db/base.py` | Ajuste: `UTCDateTime.__repr__` para las migraciones |
| `requirements.txt` | Nueva dependencia: `alembic` |
