from __future__ import annotations

from pydantic import BaseModel, field_validator

SOURCE = "metro_madrid"


class _Estacion(BaseModel):
    nombre: str
    slug: str


class Params(BaseModel):
    estaciones: list[_Estacion]
    anyo_url: str

    @field_validator("estaciones")
    @classmethod
    def al_menos_una(cls, v: list) -> list:
        if not v:
            raise ValueError("estaciones no puede estar vacío")
        return v

    @field_validator("anyo_url")
    @classmethod
    def url_tiene_placeholder(cls, v: str) -> str:
        if "{year}" not in v:
            raise ValueError("anyo_url debe contener el marcador {year}")
        return v
