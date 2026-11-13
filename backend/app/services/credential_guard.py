"""
Salvaguarda central de credenciales de fuentes de red (J07).

Una fuente de red (RTSP, HTTP) puede traer usuario y contraseña dentro de la
URL (`rtsp://admin:clave@host/stream`) o en parámetros (`?password=...`). La
política aprobada de datos sensibles exige que esas credenciales nunca se
almacenen ni se expongan en respuestas, historial, métricas, logs ni
documentación: la base guarda solo la fuente pública y, aparte, el *nombre* de
un secreto (`credential_ref`), nunca la credencial misma.

Antes de J07, cada capa tenía su propia copia de las reglas. Aquí se centralizan
en un solo lugar, con una batería de pruebas, y todas las capas lo usan. Dos
operaciones:

  - `contains_credentials(valor)` / `reject_credentials(campo, valor)`: detectar
    y rechazar credenciales en lo que se va a almacenar (fuentes, parámetros,
    mensajes de error, atributos).
  - `redact(texto)` / `redact_source(fuente)`: enmascarar credenciales en lo que
    sí sale pero podría arrastrarlas sin querer (logs, métricas, mensajes).

La diferencia: lo que el usuario controla y no debe traer credenciales se
*rechaza* (para avisarle); lo que el sistema genera y podría arrastrarlas por
accidente se *enmascara* (para no fallar, pero tampoco filtrar).
"""

from __future__ import annotations

import re
from typing import Any, Optional

MASK = "***"

# usuario:clave@ o usuario@ tras un esquema, en una URL
_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s@'\"]+@")

# nombres de parámetro o de campo que indican una credencial
_SENSITIVE_NAME = re.compile(
    r"(pass(word|wd)?|pwd|token|secret|api[_-]?key|private[_-]?key|auth|"
    r"credential|user(name)?|login|session|sig(nature)?|bearer)",
    re.IGNORECASE,
)

# parámetro sensible con valor dentro de una URL: ?token=abc, &password=x
_SENSITIVE_QUERY = re.compile(
    r"(?P<prefix>[?&][a-zA-Z0-9_\-]*"
    r"(?:pass(?:word|wd)?|pwd|token|secret|api[_-]?key|private[_-]?key|auth|"
    r"credential|user(?:name)?|login|session|sig(?:nature)?|bearer)"
    r"[a-zA-Z0-9_\-]*=)[^&\s'\"]+",
    re.IGNORECASE,
)

# forma válida de una referencia a un secreto: NOMBRE_EN_MAYUSCULAS
_CREDENTIAL_REF = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class CredentialLeakError(ValueError):
    """Se intentó almacenar una credencial en un campo que no debe contenerla."""

    def __init__(self, field: str, detail: str) -> None:
        self.field = field
        super().__init__(
            f"No se permiten credenciales en '{field}' ({detail}). "
            "Guarde la fuente pública y el nombre del secreto en credential_ref."
        )


# ── Detección ─────────────────────────────────────────────────────────────────

def find_credentials(value: Any, path: str = "valor") -> Optional[str]:
    """
    Busca credenciales en un valor (texto, dict o lista, de forma recursiva).

    Returns:
        Una descripción de dónde se encontró, o None si está limpio.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if _USERINFO.search(value):
            return f"{path}: usuario o contraseña dentro de una URL"
        if _SENSITIVE_QUERY.search(value):
            return f"{path}: parámetro con credenciales dentro de una URL"
        return None
    if isinstance(value, dict):
        for k, item in value.items():
            # Un campo cuyo NOMBRE indica credencial y trae texto no vacío
            if _SENSITIVE_NAME.search(str(k)) and isinstance(item, str) and item.strip():
                return f"{path}.{k}: el nombre del campo indica una credencial"
            found = find_credentials(item, f"{path}.{k}")
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            found = find_credentials(item, f"{path}[{i}]")
            if found:
                return found
    return None


def contains_credentials(value: Any) -> bool:
    return find_credentials(value) is not None


def reject_credentials(field: str, value: Any) -> Any:
    """Devuelve el valor si está limpio; si no, lanza CredentialLeakError."""
    found = find_credentials(value, field)
    if found:
        raise CredentialLeakError(field, found)
    return value


def is_valid_credential_ref(value: Optional[str]) -> bool:
    """Una referencia válida es el NOMBRE de un secreto en mayúsculas, no la credencial."""
    return value is not None and bool(_CREDENTIAL_REF.match(value))


# ── Enmascarado ───────────────────────────────────────────────────────────────

def redact_source(source: Optional[str]) -> Optional[str]:
    """
    Versión pública de una fuente, sin credenciales.

    - `0`, rutas de archivo, URLs sin credenciales → se devuelven igual.
    - `rtsp://admin:clave@host/s` → `rtsp://***@host/s`
    - `rtsp://host/s?token=abc&canal=1` → `rtsp://host/s?token=***&canal=1`
    """
    if source is None or "://" not in source:
        return source
    out = _USERINFO.sub(lambda m: f"{m.group('scheme')}{MASK}@", source)
    out = _SENSITIVE_QUERY.sub(lambda m: f"{m.group('prefix')}{MASK}", out)
    return out


def redact(text: Optional[str], *sources: Optional[str]) -> Optional[str]:
    """
    Enmascara credenciales dentro de un texto libre (logs, mensajes, métricas).

    Reemplaza cada aparición de las `sources` por su versión pública y, por si el
    texto trae otra URL con credenciales, también enmascara esas.
    """
    if not text:
        return text
    for source in sources:
        public = redact_source(source)
        if source and public != source:
            text = text.replace(source, public)
    text = _USERINFO.sub(lambda m: f"{m.group('scheme')}{MASK}@", text)
    text = _SENSITIVE_QUERY.sub(lambda m: f"{m.group('prefix')}{MASK}", text)
    return text


def redact_deep(value: Any) -> Any:
    """
    Enmascara credenciales en una estructura (dict, lista, texto), recursivamente.

    Útil para limpiar un objeto antes de enviarlo a logs o métricas. Un campo
    cuyo nombre indica credencial se enmascara entero; los textos se pasan por
    `redact`.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        out = {}
        for k, item in value.items():
            if _SENSITIVE_NAME.search(str(k)) and isinstance(item, str) and item.strip():
                out[k] = MASK
            else:
                out[k] = redact_deep(item)
        return out
    if isinstance(value, list):
        return [redact_deep(i) for i in value]
    if isinstance(value, tuple):
        return tuple(redact_deep(i) for i in value)
    return value
