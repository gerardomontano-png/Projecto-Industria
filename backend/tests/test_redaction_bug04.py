"""
Prueba de regresión para BUG-04: el enmascarado no debe dejar escapar
parte de la contraseña cuando esta contiene el carácter "@".

Ejecutar:
    cd backend
    python -m pytest tests/test_redaction_bug04.py -v
"""

import pytest

from app.services.redaction import redact_source, redact_text

CLAVE = "p@ss2024"
URL = f"rtsp://admin:{CLAVE}@10.0.0.9/stream"


def test_bug04_clave_con_arroba_no_se_escapa_en_texto():
    salida = redact_text(f"Error al leer {URL}")
    assert CLAVE not in salida
    assert "ss2024" not in salida            # ni un fragmento de la clave
    assert "rtsp://***@10.0.0.9/stream" in salida
    assert "10.0.0.9" in salida              # el host sí se conserva


def test_bug04_clave_con_arroba_no_se_escapa_en_source():
    salida = redact_source(URL)
    assert CLAVE not in salida
    assert salida == "rtsp://***@10.0.0.9/stream"


@pytest.mark.parametrize("texto, prohibido", [
    ("rtsp://admin:clave@10.0.0.9/s", "clave"),
    ("rtsp://admin:p@ss@10.0.0.9/s?canal=1", "p@ss"),
    ("rtsp://u:pa@ss@host/s y rtsp://x:cl@ve@host2/s", "ve"),
])
def test_bug04_variantes(texto, prohibido):
    assert prohibido not in redact_text(texto)


def test_sin_credenciales_no_se_toca():
    assert redact_text("rtsp://10.0.0.9/stream") == "rtsp://10.0.0.9/stream"
    assert redact_source("rtsp://10.0.0.9/stream") == "rtsp://10.0.0.9/stream"
