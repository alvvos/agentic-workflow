"""
Recurso genérico de eventos — despachador para cualquier módulo en fuentes_eventos/.

Configuración en fuentes.config:
  modulo:   str   nombre del módulo en src.data_processing.fuentes_eventos.<modulo>
                  El módulo debe exponer: sync(ubicacion, cfg, date_from, date_to)
                  → tuple[dict[date, dict], list[dict]]

Configuración por ubicación (en ubicacion["params"]):
  Cualquier clave que el módulo concreto espere (equipos, sedes, etc.).

Para añadir una nueva fuente de eventos: crear el módulo en fuentes_eventos/ con
la función sync(), añadir una fila en fuentes con tipo_conector="eventos" y
modulo="<nombre_modulo>" en config. Cero cambios de Python en el pipeline.

Interfaz pública: source(ubicaciones, cfg, date_from, date_to) -> dlt.Source
"""

from __future__ import annotations

import importlib
from datetime import date

import dlt


def _collect(
    ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date
) -> tuple[list[dict], list[dict]]:
    modulo_nombre = cfg.get("modulo")
    if not modulo_nombre:
        return [], []

    cliente = importlib.import_module(f"src.data_processing.fuentes_eventos.{modulo_nombre}")

    señales: list[dict] = []
    eventos: list[dict] = []

    for ubi in ubicaciones:
        ubi_id = ubi["ubicacion_id"]
        loc_cfg = {**cfg, **ubi.get("params", {})}
        daily, raw_rows = cliente.sync(ubi, loc_cfg, date_from, date_to)

        for d, vals in daily.items():
            for señal_id, valor in vals.items():
                señales.append(
                    {
                        "fecha": d.isoformat(),
                        "ubicacion_id": ubi_id,
                        "señal_id": señal_id,
                        "valor": float(valor),
                    }
                )

        for row in raw_rows:
            eventos.append(
                {
                    "ubicacion_id": ubi_id,
                    "pais_codigo": ubi.get("pais_codigo", "ES"),
                    "evento_key": row["evento_key"],
                    "fecha_inicio": str(row["fecha_inicio"]),
                    "fecha_fin": str(row.get("fecha_fin", row["fecha_inicio"])),
                    "fuente": row.get("fuente", modulo_nombre),
                    "source_key": row["source_key"],
                    "metadata": row.get("metadata", {}),
                }
            )

    return señales, eventos


@dlt.source
def source(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    señales, eventos = _collect(ubicaciones, cfg, date_from, date_to)

    @dlt.resource(
        name="señal", write_disposition="merge", primary_key=["fecha", "ubicacion_id", "señal_id"]
    )
    def señal_res():
        yield from señales

    @dlt.resource(name="evento", write_disposition="merge", primary_key=["source_key"])
    def evento_res():
        yield from eventos

    yield señal_res()
    yield evento_res()
