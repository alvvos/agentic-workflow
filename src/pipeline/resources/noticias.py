"""
Recurso dlt — Newsdata.io noticias locales.

Configuración en fuentes.config:
  max_paginas:  int    páginas por ubicación (default 3)
  categorias:   [str]  filtro de categorías Newsdata (opcional)

Interfaz pública: source(ubicaciones, cfg, date_from, date_to) -> dlt.Source
"""

from __future__ import annotations

from datetime import date

import dlt


@dlt.source
def source(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):  # noqa: ARG001
    @dlt.resource(
        name="noticia",
        write_disposition="merge",
        primary_key=["article_id", "ubicacion_id"],
    )
    def noticia_res():
        from src.conectores.newsdata import sync

        for ubi in ubicaciones:
            yield from sync(ubi, cfg)

    yield noticia_res()
