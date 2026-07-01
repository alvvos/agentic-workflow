from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Respuesta(BaseModel, Generic[T]):
    ok: bool = True
    datos: T


class Error(BaseModel):
    ok: bool = False
    mensaje: str
    detalle: str | None = None
