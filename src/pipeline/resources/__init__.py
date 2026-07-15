"""
Registro de recursos dlt por tipo_conector.

El runner resuelve tipo_conector → módulo → función source().
Para añadir un nuevo tipo: añadir entrada aquí y crear el módulo correspondiente.
"""

from __future__ import annotations

import importlib

_REGISTRO: dict[str, str] = {
    "http_json": "http_json",
    "meteorologia": "meteorologia",
}


def get_source_fn(tipo: str):
    modulo_nombre = _REGISTRO.get(tipo)
    if not modulo_nombre:
        raise ValueError(f"Tipo de conector desconocido: {tipo!r}")
    modulo = importlib.import_module(f"src.pipeline.resources.{modulo_nombre}")
    return modulo.source
