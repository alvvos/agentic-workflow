from __future__ import annotations

from pydantic import BaseModel, field_validator

SOURCE = "puertos_estado"

_AP_VALIDAS = {
    "Málaga",
    "Barcelona",
    "Valencia",
    "Palma",
    "Baleares",
    "Sevilla",
    "Las Palmas",
    "Santa Cruz de Tenerife",
    "Cádiz",
    "Cartagena",
    "Almería",
    "Motril",
    "Alicante",
    "Tarragona",
}


class Params(BaseModel):
    port_authority: str

    @field_validator("port_authority")
    @classmethod
    def ap_valida(cls, v: str) -> str:
        if v not in _AP_VALIDAS:
            raise ValueError(
                f"'{v}' no reconocida. " f"Autoridades válidas: {', '.join(sorted(_AP_VALIDAS))}"
            )
        return v
