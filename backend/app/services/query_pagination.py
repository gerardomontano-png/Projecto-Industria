"""
Paginación, ordenamiento y límites de consulta (J05).

Reglas que hace cumplir, para que ninguna consulta devuelva un conjunto
ilimitado ni una página inestable:

  - Límites: cada consulta trae un tamaño de página (`limit`) acotado entre 1 y
    `MAX_PAGE_SIZE`; si no se pide, se usa `DEFAULT_PAGE_SIZE`.
  - Ordenamiento: solo se permite ordenar por campos de una lista blanca, en
    dirección asc o desc. Pedir otro campo es un error controlado, no un
    ordenamiento silencioso por un campo arbitrario.
  - Paginación estable: además del clásico offset, se ofrece un cursor opaco
    que codifica la posición exacta (valor de orden + id), para que agregar
    filas nuevas no desplace ni repita resultados entre páginas.

Este módulo no conoce el modelo de detección: trabaja con cualquier consulta
que declare sus campos ordenables. Lo usa `EventQuery` de J04/J05.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

# Límites globales: ninguna consulta puede pedir más de esto
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class PaginationError(ValueError):
    """Un parámetro de paginación u ordenamiento es inválido."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class SortField:
    """Un campo por el que se puede ordenar, con su columna real en el modelo."""

    name: str          # nombre público, el que pide el cliente
    column: Any        # la columna de SQLAlchemy
    is_unique: bool = False  # True si por sí solo ya desempata (p. ej. el id)


@dataclass(frozen=True)
class SortOrder:
    field: SortField
    direction: SortDirection = SortDirection.DESC


def normalize_limit(limit: Optional[int]) -> int:
    """
    Devuelve un tamaño de página válido.

    None → el valor por defecto. Fuera de rango → error controlado. Así, el
    tope máximo se aplica siempre, aunque el cliente pida un número enorme.
    """
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise PaginationError("limit", "limit debe ser un número entero.")
    if limit < 1:
        raise PaginationError("limit", "limit debe ser al menos 1.")
    if limit > MAX_PAGE_SIZE:
        raise PaginationError(
            "limit", f"limit no puede superar {MAX_PAGE_SIZE} (se pidió {limit})."
        )
    return limit


def normalize_offset(offset: Optional[int]) -> int:
    if offset is None:
        return 0
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise PaginationError("offset", "offset debe ser un entero no negativo.")
    return offset


def resolve_sort(
    sort_by: Optional[str],
    direction: Optional[str],
    allowed: dict[str, SortField],
    default: SortOrder,
) -> SortOrder:
    """
    Convierte lo que pide el cliente en un orden válido, o falla.

    Solo se aceptan campos de `allowed`; cualquier otro da PaginationError, en
    vez de ordenar por algo inesperado.
    """
    if sort_by is None and direction is None:
        return default

    field = default.field
    if sort_by is not None:
        if sort_by not in allowed:
            opciones = ", ".join(sorted(allowed))
            raise PaginationError(
                "sort_by", f"No se puede ordenar por '{sort_by}'. Opciones: {opciones}."
            )
        field = allowed[sort_by]

    dir_value = default.direction
    if direction is not None:
        try:
            dir_value = SortDirection(direction)
        except ValueError:
            raise PaginationError("sort_dir", "La dirección debe ser 'asc' o 'desc'.")

    return SortOrder(field=field, direction=dir_value)


# ── Cursor ────────────────────────────────────────────────────────────────────

def encode_cursor(sort_value: Any, row_id: str) -> str:
    """
    Codifica la posición de una fila en un cursor opaco (texto base64).

    Guarda el valor del campo de orden y el id, que juntos desempatan de forma
    única. El cliente lo trata como una cadena sin significado.
    """
    if isinstance(sort_value, datetime):
        payload = {"t": "dt", "v": sort_value.astimezone(timezone.utc).isoformat()}
    else:
        payload = {"t": "raw", "v": sort_value}
    payload["id"] = row_id
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[Any, str]:
    """Decodifica un cursor. Un cursor corrupto es un error controlado."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        value = payload["v"]
        if payload.get("t") == "dt":
            value = datetime.fromisoformat(value)
        return value, payload["id"]
    except (ValueError, KeyError, TypeError):
        raise PaginationError("cursor", "El cursor es inválido o está corrupto.")


@dataclass
class Page:
    """Una página de resultados y lo necesario para pedir la siguiente."""

    items: list
    total: int
    limit: int
    offset: int
    next_cursor: Optional[str] = None
    sort_by: Optional[str] = None
    sort_dir: Optional[str] = None

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    def to_dict(self, item_to_dict) -> dict:
        return {
            "items": [item_to_dict(i) for i in self.items],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "sort": {"by": self.sort_by, "dir": self.sort_dir},
        }
