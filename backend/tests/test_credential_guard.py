"""
Pruebas de la salvaguarda de credenciales de fuentes de red — J07.

Verifican la salvaguarda central de forma exhaustiva y, sobre un escenario
completo con una cámara IP, que una contraseña de prueba no aparezca en ninguna
de las superficies que el criterio exige proteger: respuestas, historial de la
base, métricas, logs y documentación.

Criterios cubiertos:
  C1  Las credenciales no aparecen en respuestas ni registros.
  C2  La persistencia almacena únicamente la referencia segura aprobada.
  C3  Las pruebas verifican serialización, errores, logs e historial.

Ejecutar:
    cd backend
    python -m pytest tests/test_credential_guard.py -v
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, create_db_engine
from app.db.models import Camera, CameraStatus, CredentialLeakError, SourceType
from app.services.credential_guard import (
    contains_credentials,
    find_credentials,
    is_valid_credential_ref,
    redact,
    redact_deep,
    redact_source,
    reject_credentials,
)
from app.services.source_admin import SourceAdminService
from app.services.source_schemas import SourceCreate, SourceUpdate, SourceValidationError

SECRETO = "Sup3rClave!"
TOKEN = "T0k3nSecreto"
URL_CON_SECRETO = f"rtsp://admin:{SECRETO}@10.0.0.5:554/stream?token={TOKEN}&canal=1"
SECRETOS = (SECRETO, TOKEN)

DOCS = Path(__file__).resolve().parents[1] / "docs"


def sin_secretos(*objetos) -> bool:
    texto = json.dumps(objetos, default=str)
    return not any(s in texto for s in SECRETOS)


# ── Detección ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "valor",
    [
        "rtsp://admin:clave@10.0.0.5/s",
        "rtsp://admin@10.0.0.5/s",
        "rtsp://10.0.0.5/s?user=admin&password=x",
        "http://h/v?token=abc",
        "rtsp://u:p@ss@h/s",
        {"headers": {"Authorization": "Bearer abc"}},
        ["ok", {"password": "x"}],
        {"nested": [{"api_key": "z"}]},
    ],
)
def test_detecta_credenciales(valor):
    assert contains_credentials(valor)


@pytest.mark.parametrize(
    "valor",
    [
        "0",
        "C:/videos/linea1.mp4",
        "rtsp://10.0.0.5:554/stream",
        "rtsp://10.0.0.5/s?canal=2&fps=30",
        {"conf": 0.3, "roi": [[0, 0], [10, 10]]},
        {"token_count": 5},            # nombre sensible, pero valor numérico
        {"password": ""},              # nombre sensible, pero vacío
        ["pieza", "tornillo"],
        None,
    ],
)
def test_no_marca_lo_limpio(valor):
    assert not contains_credentials(valor)


def test_reject_devuelve_el_valor_limpio_o_lanza():
    assert reject_credentials("source", "rtsp://h/s") == "rtsp://h/s"
    with pytest.raises(CredentialLeakError) as info:
        reject_credentials("source", "rtsp://a:b@h/s")
    assert info.value.field == "source"


def test_referencia_valida_es_un_nombre_no_una_credencial():
    assert is_valid_credential_ref("CAMARA_LINEA1_RTSP")
    assert not is_valid_credential_ref("admin:clave")
    assert not is_valid_credential_ref("clave123")
    assert not is_valid_credential_ref("minusculas")
    assert not is_valid_credential_ref(None)


# ── Enmascarado ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "fuente, esperado",
    [
        ("0", "0"),
        ("rtsp://10.0.0.5/s", "rtsp://10.0.0.5/s"),
        ("rtsp://admin:clave@10.0.0.5:554/s", "rtsp://***@10.0.0.5:554/s"),
        ("rtsp://u@10.0.0.5/s", "rtsp://***@10.0.0.5/s"),
        ("rtsp://h/s?user=a&password=x&canal=1", "rtsp://h/s?user=***&password=***&canal=1"),
    ],
)
def test_redact_source(fuente, esperado):
    assert redact_source(fuente) == esperado


def test_redact_en_texto_libre():
    texto = f"No se pudo conectar a {URL_CON_SECRETO}; reintente con http://u:p@h/x?token=z"
    limpio = redact(texto, URL_CON_SECRETO)
    assert sin_secretos(limpio)
    assert "p@h" not in limpio and "token=z" not in limpio
    assert "10.0.0.5" in limpio  # lo útil para diagnosticar se conserva


def test_redact_deep_en_estructuras():
    datos = {
        "camera": "rtsp://admin:clave@h/s",
        "headers": {"Authorization": "Bearer zzz", "X-Trace": "ok"},
        "list": ["normal", "http://x:y@h/p"],
    }
    limpio = redact_deep(datos)
    assert "clave" not in json.dumps(limpio)
    assert "zzz" not in json.dumps(limpio)
    assert limpio["headers"]["X-Trace"] == "ok"   # lo no sensible se conserva


# ── C2: la base almacena solo la referencia ──────────────────────────────────

@pytest.fixture
def db():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_c2_el_modelo_rechaza_credenciales_en_la_fuente(db):
    with pytest.raises(CredentialLeakError):
        Camera(name="IP", source=URL_CON_SECRETO, source_type=SourceType.RTSP)


def test_c2_el_modelo_solo_acepta_una_referencia_por_nombre(db):
    cam = Camera(
        name="Línea 3", source="rtsp://10.0.0.5:554/stream",
        source_type=SourceType.RTSP, credential_ref="CAMARA_LINEA3_RTSP",
    )
    db.add(cam)
    db.commit()
    assert cam.credential_ref == "CAMARA_LINEA3_RTSP"
    for malo in ("admin:clave", "clave123", "rtsp://a:b@h"):
        with pytest.raises(ValueError):
            cam.credential_ref = malo


def test_c2_el_servicio_rechaza_credenciales_al_registrar_y_actualizar(db):
    svc = SourceAdminService(db)
    with pytest.raises(SourceValidationError) as info:
        svc.register(SourceCreate(name="IP", source_type=SourceType.RTSP, source=URL_CON_SECRETO))
    assert info.value.field == "source"

    ok = svc.register(SourceCreate(
        name="IP", source_type=SourceType.RTSP,
        source="rtsp://10.0.0.5:554/stream", credential_ref="CAMARA_IP_RTSP"))
    with pytest.raises(SourceValidationError):
        svc.update(ok.id, SourceUpdate(source=URL_CON_SECRETO))


# ── C1 y C3: ninguna superficie expone el secreto ────────────────────────────

def test_c1_la_respuesta_del_servicio_no_lleva_la_credencial(db):
    svc = SourceAdminService(db)
    r = svc.register(SourceCreate(
        name="IP", source_type=SourceType.RTSP,
        source="rtsp://10.0.0.5:554/stream", credential_ref="CAMARA_IP_RTSP"))

    salida = r.to_dict()
    assert salida["has_credentials"] is True
    assert salida["credential_ref"] == "CAMARA_IP_RTSP"  # un nombre
    assert "password" not in salida
    assert sin_secretos(salida)


def test_c3_escenario_completo_ninguna_superficie_filtra(db, caplog):
    """
    Respuestas, historial (base), métricas (serialización), logs y errores:
    el secreto no aparece en ninguno.
    """
    caplog.set_level(logging.DEBUG)
    svc = SourceAdminService(db)

    # 1) Registrar correctamente (fuente pública + referencia)
    r = svc.register(SourceCreate(
        name="Cámara IP", source_type=SourceType.RTSP,
        source="rtsp://10.0.0.5:554/stream", credential_ref="CAMARA_IP_RTSP"))

    # 2) Intentos de colar el secreto: todos rechazados ANTES de la base
    for intento in (
        lambda: svc.update(r.id, SourceUpdate(source=URL_CON_SECRETO)),
        lambda: svc.register(SourceCreate(
            name="Otra", source_type=SourceType.RTSP, source=URL_CON_SECRETO)),
    ):
        with pytest.raises(SourceValidationError):
            intento()

    # 3) Respuestas (serialización) e historial (consulta)
    respuestas = [svc.get(r.id).to_dict(), *(s.to_dict() for s in svc.list())]

    # 4) Métricas simuladas: un dict con la fuente, pasado por el enmascarado
    metricas = redact_deep({
        "camera_id": r.id, "source": "rtsp://10.0.0.5:554/stream",
        "last_error": f"timeout al abrir {URL_CON_SECRETO}",
    })

    # 5) Un log que, por error, incluyó la URL completa → se enmascara
    logging.getLogger("demo").info("conectando a %s", redact(URL_CON_SECRETO))

    # 6) La fila en la base
    fila = db.get(Camera, r.id)
    base = f"{fila.source} {fila.credential_ref} {fila.name}"

    assert sin_secretos(respuestas, metricas, base, caplog.text)
    assert "10.0.0.5" in json.dumps(respuestas)  # lo público sí se conserva


# ── Documentación ─────────────────────────────────────────────────────────────

def test_docs_no_contienen_credenciales_de_ejemplo():
    """
    Ningún documento del proyecto debe traer una URL de ejemplo con credenciales
    reales. Los ejemplos usan la forma enmascarada (rtsp://***@...) o referencias.
    """
    import re
    # user:pass@ con al menos una minúscula (un placeholder como USUARIO:CLAVE@ no cuenta)
    patron = re.compile(r"[a-zA-Z]+://(?=[^/\s@]*[a-z])[^/\s@*'\"]+:[^/\s@*'\"]+@")
    ofensores = []
    for doc in DOCS.glob("*.md"):
        for n, linea in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if patron.search(linea):
                ofensores.append(f"{doc.name}:{n}")
    assert ofensores == [], f"Credenciales en documentación: {ofensores}"
