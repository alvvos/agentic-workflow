"""
Infraestructura dlt: factory de pipeline y destino personalizado.

El destino escribe directamente a las tablas del proyecto
(valores_señales, eventos) en lugar de crear tablas propias de dlt.
dlt sigue gestionando el estado incremental y los reintentos.
"""

from __future__ import annotations

import json
import os
from typing import Any

import dlt
from dotenv import load_dotenv

load_dotenv()


def _pg_url() -> str:
    from urllib.parse import quote_plus

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5433")
    user = os.getenv("DB_USER", "admin")
    pwd = quote_plus(os.getenv("DB_PASSWORD", ""))
    name = os.getenv("DB_NAME", "reporting")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


# ── Destino personalizado ─────────────────────────────────────────────────────


@dlt.destination(batch_size=500, loader_file_format="jsonl")
class SeñalesDestino:
    """
    Destino dlt que enruta cada tabla lógica a la tabla real del proyecto.

    Los recursos deben emitir filas con shape:
      señal   → {fecha, ubicacion_id, señal_id, valor}
      evento  → {ubicacion_id, pais_codigo, evento_key, fecha_inicio, fecha_fin,
                  fuente, source_key, metadata}
    """

    def __init__(self, config: dict[str, Any], credentials: Any) -> None:  # noqa: ARG002
        from src.db.store import get_conn

        self._conn = get_conn()

    def initialize_storage_with_extracted_records(self, schema: Any) -> None:  # noqa: ARG002
        pass

    def start_file_load(self, table: Any, file_path: str, *args: Any, **kwargs: Any) -> None:
        name = table["name"]
        rows = _parse_jsonl(file_path)
        if name == "señal":
            self._upsert_señales(rows)
        elif name == "evento":
            self._upsert_eventos(rows)
        elif name == "noticia":
            self._upsert_noticias(rows)

    def complete_load(self, load_id: str) -> None:  # noqa: ARG002
        pass

    # ── writes ────────────────────────────────────────────────────────────────

    def _upsert_señales(self, rows: list[dict]) -> None:
        datos = [
            (str(r["fecha"]), r["ubicacion_id"], r["señal_id"], float(r["valor"]))
            for r in rows
            if r.get("señal_id") and r.get("valor") is not None
        ]
        if not datos:
            return
        self._conn.executemany(
            """
            INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fecha, ubicacion_id, señal_id)
            DO UPDATE SET
                valor      = GREATEST(valores_señales.valor, excluded.valor),
                ingerido_en = NOW()
            """,
            datos,
        )

    def _upsert_eventos(self, rows: list[dict]) -> None:
        datos = [
            (
                r["ubicacion_id"],
                r.get("pais_codigo", ""),
                r["evento_key"],
                str(r["fecha_inicio"]),
                str(r.get("fecha_fin", r["fecha_inicio"])),
                json.dumps(r.get("metadata", {}), ensure_ascii=False),
                r.get("fuente", ""),
                r["source_key"],
            )
            for r in rows
            if r.get("source_key")
        ]
        if not datos:
            return
        self._conn.executemany(
            """
            INSERT INTO eventos
                (ubicacion_id, pais_codigo, evento_key,
                 fecha_inicio, fecha_fin, metadata, fuente, clave_fuente)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (clave_fuente) DO NOTHING
            """,
            datos,
        )

    def _upsert_noticias(self, rows: list[dict]) -> None:
        datos = [
            (
                r["article_id"],
                r["ubicacion_id"],
                r.get("titulo"),
                r.get("descripcion"),
                r.get("url"),
                r.get("publicada_en"),
                r.get("fuente_id"),
                r.get("fuente_nombre"),
                r.get("categorias"),
                r.get("idioma"),
                r.get("contenido"),
            )
            for r in rows
            if r.get("article_id") and r.get("ubicacion_id")
        ]
        if not datos:
            return
        self._conn.executemany(
            """
            INSERT INTO noticias
                (article_id, ubicacion_id, titulo, descripcion, url,
                 publicada_en, fuente_id, fuente_nombre, categorias, idioma, contenido)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (article_id, ubicacion_id) DO NOTHING
            """,
            datos,
        )


def _parse_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── Factory ───────────────────────────────────────────────────────────────────


def make_pipeline(nombre: str) -> dlt.Pipeline:
    return dlt.pipeline(
        pipeline_name=nombre,
        destination=SeñalesDestino(),
        pipelines_dir="/tmp/dlt_pipelines",
    )
