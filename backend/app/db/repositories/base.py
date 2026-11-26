"""Repositorio genérico con las operaciones comunes a todas las entidades."""

from __future__ import annotations

from typing import Generic, Optional, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """
    Base de los repositorios.

    No hace commit: solo prepara los cambios en la sesión que recibe. El
    `flush` envía el INSERT a la base para que las restricciones se verifiquen
    de inmediato y la fila reciba sus valores por defecto, pero la transacción
    sigue abierta hasta que quien la controla haga commit.
    """

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: ModelT, *, flush: bool = True) -> ModelT:
        self.session.add(entity)
        if flush:
            self.session.flush()
        return entity

    def add_all(self, entities: Sequence[ModelT], *, flush: bool = True) -> Sequence[ModelT]:
        self.session.add_all(entities)
        if flush:
            self.session.flush()
        return entities

    def get(self, entity_id: str) -> Optional[ModelT]:
        return self.session.get(self.model, entity_id)

    def list(self, *, limit: Optional[int] = None, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(self.model)) or 0

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()
