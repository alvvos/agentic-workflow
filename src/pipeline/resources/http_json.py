"""
Recurso genérico para cualquier API REST JSON descrita en fuentes.config.

Configuración esperada en fuentes.config:
  base_url:       str          URL base de la API
  path:           str          path del endpoint (puede contener {lat}, {lon}, {date_from}, etc.)
  params:         dict         parámetros de query (valores pueden contener {placeholders})
  auth_env:       str|null     nombre de la variable de entorno con la API key
  auth_header:    str          nombre del header de autenticación
  response_path:  [str]        ruta para llegar al array de items en la respuesta
  field_map:      dict         {señal_id: "campo_api" | valor_literal}
  pagination:     dict|null    {tipo: "page"|"offset", param: str, size: int}
  timeout:        int          timeout HTTP en segundos

Interfaz pública requerida por el runner:
  source(ubicaciones, cfg, date_from, date_to) -> dlt.Source
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import dlt
import requests


def _render(template: Any, ctx: dict) -> Any:
    if isinstance(template, str):
        return template.format_map(ctx)
    return template


def _build_ctx(ubicacion: dict, date_from: date, date_to: date) -> dict:
    return {
        "lat": ubicacion.get("lat", ""),
        "lon": ubicacion.get("lon", ""),
        "ciudad": ubicacion.get("city", ""),
        "pais": ubicacion.get("pais_codigo", ""),
        "region": ubicacion.get("region_code", ""),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "year": date_from.year,
    }


def _fetch_paginated(cfg: dict, ctx: dict) -> list[dict]:
    url = _render(cfg["base_url"], ctx) + _render(cfg.get("path", ""), ctx)
    params = {k: _render(v, ctx) for k, v in cfg.get("params", {}).items()}

    headers: dict[str, str] = {}
    if cfg.get("auth_env"):
        headers[cfg["auth_header"]] = os.getenv(cfg["auth_env"], "")

    timeout = int(cfg.get("timeout", 15))
    pag = cfg.get("pagination")
    items: list[dict] = []

    page = 0
    while True:
        if pag:
            params[pag["param"]] = page if pag["tipo"] == "page" else page * pag.get("size", 100)

        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                break
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        for key in cfg.get("response_path", []):
            data = data.get(key, []) if isinstance(data, dict) else []

        batch = data if isinstance(data, list) else []
        items.extend(batch)

        if not pag or len(batch) < pag.get("size", 100):
            break
        page += 1

    return items


def _map_row(item: dict, field_map: dict, ubicacion_id: str) -> list[dict]:
    rows = []
    for señal_id, src in field_map.items():
        valor = item.get(src) if isinstance(src, str) else src
        if valor is not None:
            rows.append(
                {
                    "fecha": item.get("fecha") or item.get("date") or item.get("time"),
                    "ubicacion_id": ubicacion_id,
                    "señal_id": señal_id,
                    "valor": float(valor),
                }
            )
    return rows


@dlt.resource(
    name="señal", write_disposition="merge", primary_key=["fecha", "ubicacion_id", "señal_id"]
)
def _resource(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    field_map: dict = cfg.get("field_map", {})
    for ubi in ubicaciones:
        ctx = _build_ctx(ubi, date_from, date_to)
        for item in _fetch_paginated(cfg, ctx):
            yield from _map_row(item, field_map, ubi["ubicacion_id"])


@dlt.source
def source(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    yield _resource(ubicaciones, cfg, date_from, date_to)
