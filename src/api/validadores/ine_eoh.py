from __future__ import annotations

from pydantic import BaseModel

SOURCE = "ine_eoh"


class Params(BaseModel):
    provincia_nombre: str
    tabla_viajeros: int = 2078
    tabla_pernoctaciones: int = 2078
    municipio_codigo: str | None = None
