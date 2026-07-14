"""
Conector Newsdata.io — noticias locales por ciudad/país.

Requiere NEWSDATA_API_KEY en .env.
Plan gratuito: endpoint /news, últimos 30 días, 200 req/día, 10 artículos/página.
Plan de pago: endpoint /archive con from_date/to_date histórico ilimitado.

Interfaz pública:
    TIPO = "noticias"
    sync(ubicacion, cfg) -> list[dict]
        Devuelve artículos normalizados para insertar en la tabla noticias.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

TIPO = "noticias"

_API_KEY = os.getenv("NEWSDATA_API_KEY", "")
_BASE_URL = "https://newsdata.io/api/1/news"
_TIMEOUT = 15
_DELAY = 1.0  # segundos entre páginas para respetar rate limit

_PAIS_IDIOMA: dict[str, str] = {
    "ES": "es",
    "MX": "es",
    "AR": "es",
    "CO": "es",
    "PE": "es",
    "CL": "es",
    "FR": "fr",
    "DE": "de",
    "IT": "it",
    "PT": "pt",
    "GB": "en",
    "US": "en",
    "AU": "en",
}


def _fetch_page(params: dict) -> tuple[list[dict], str | None]:
    """Llama a la API y devuelve (artículos, nextPage token o None)."""
    try:
        r = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT)
        if r.status_code == 429:
            return [], None  # rate limit — abortar sin error
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            return [], None
        return data.get("results", []), data.get("nextPage")
    except Exception:
        return [], None


def _normalizar(articulo: dict, ubicacion_id: str) -> dict | None:
    article_id = articulo.get("article_id")
    if not article_id:
        return None
    pub_raw = articulo.get("pubDate")
    return {
        "article_id": article_id,
        "ubicacion_id": ubicacion_id,
        "titulo": (articulo.get("title") or "")[:500],
        "descripcion": (articulo.get("description") or "")[:2000],
        "url": articulo.get("link") or "",
        "publicada_en": pub_raw,
        "fuente_id": articulo.get("source_id") or "",
        "fuente_nombre": articulo.get("source_name") or "",
        "categorias": json.dumps(articulo.get("category") or [], ensure_ascii=False),
        "idioma": articulo.get("language") or "",
        "contenido": (articulo.get("content") or "")[:5000],
    }


def sync(ubicacion: dict, cfg: dict) -> list[dict]:
    """
    Descarga artículos de noticias para una ubicación.

    ubicacion: {ubicacion_id, nombre, lat, lon, pais_codigo, ciudad, ...}
    cfg:       config de la fuente (max_paginas, categorias, ...)
    """
    if not _API_KEY:
        return []

    ubicacion_id = ubicacion["ubicacion_id"]
    pais = (ubicacion.get("pais_codigo") or "ES").upper()
    ciudad = ubicacion.get("ciudad") or ubicacion.get("nombre") or ""
    idioma = _PAIS_IDIOMA.get(pais, "es")
    max_paginas = int(cfg.get("max_paginas", 3))
    categorias = cfg.get("categorias") or []

    # Ventana de búsqueda: ayer y hoy
    desde = (date.today() - timedelta(days=1)).isoformat()
    hasta = date.today().isoformat()

    params: dict = {
        "apikey": _API_KEY,
        "country": pais.lower(),
        "language": idioma,
        "from_date": desde,
        "to_date": hasta,
    }
    if ciudad:
        params["q"] = ciudad
    if categorias:
        params["category"] = ",".join(categorias)

    articulos: list[dict] = []
    pagina_token: str | None = None

    for _ in range(max_paginas):
        if pagina_token:
            params["page"] = pagina_token

        resultados, next_token = _fetch_page(params)
        for art in resultados:
            norm = _normalizar(art, ubicacion_id)
            if norm:
                articulos.append(norm)

        if not next_token:
            break

        pagina_token = next_token
        time.sleep(_DELAY)

    return articulos
