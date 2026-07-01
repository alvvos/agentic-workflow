from __future__ import annotations

from pydantic import BaseModel


class UbicacionResumen(BaseModel):
    location_uuid: str
    nombre: str
    ciudad: str | None = None
    pais_codigo: str
    activa: bool


class Ubicacion(UbicacionResumen):
    org_uuid: str
    lat: float | None = None
    lon: float | None = None
    provincia: str | None = None
    direccion: str | None = None
