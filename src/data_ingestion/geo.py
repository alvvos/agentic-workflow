"""
Helpers geoespaciales: auditoría de snapshots e ingesta de datos Esri GeoEnrichment.
"""

from __future__ import annotations

import logging

log = logging.getLogger("geo")


def listar_estado(verbose: bool = True) -> list[dict]:
    """
    Devuelve una lista de dicts por ubicacion activa:
      ubicacion_id, nombre, tiene_datos (bool), n_features (int), actualizado_en
    """
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute(
            """
        SELECT u.ubicacion_id, u.nombre,
               COUNT(s.señal_id)      AS n_features,
               MAX(s.actualizado_en)  AS actualizado_en
          FROM ubicaciones u
          LEFT JOIN snapshots_geo s ON s.ubicacion_id = u.ubicacion_id
         WHERE u.activa = TRUE
         GROUP BY u.ubicacion_id, u.nombre
         ORDER BY u.nombre
        """
        )
        .fetchall()
    )

    estado = []
    for ubicacion_id, nombre, n, actualizado_en in rows:
        entry = {
            "ubicacion_id": ubicacion_id,
            "nombre": nombre,
            "tiene_datos": n > 0,
            "n_features": n,
            "actualizado_en": str(actualizado_en)[:10] if actualizado_en else None,
        }
        if verbose:
            mark = "✓" if n > 0 else "✗"
            ts = f" · {entry['actualizado_en']}" if entry["actualizado_en"] else ""
            print(f"  {mark} {nombre} ({n} features{ts})")
        estado.append(entry)

    return estado


def calcular_scores_poi(ubicacion_id: str) -> dict[str, float]:
    """
    Cuenta POIs activos por categoría funcional y devuelve {señal_id: count}.
    Listo para merge con los valores de GeoEnrichment antes de ingestar.
    """
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute(
            """
            SELECT categoria, COUNT(*) AS n
            FROM puntos_interes
            WHERE ubicacion_id = ? AND activo = TRUE
            GROUP BY categoria
            """,
            [ubicacion_id],
        )
        .fetchall()
    )

    by_cat = {cat: n for cat, n in rows}

    return {
        "n_nodos_transporte": float(by_cat.get("metro", 0) + by_cat.get("transporte_bus", 0)),
        "n_restauracion": float(by_cat.get("restauracion", 0)),
        "n_atracciones": float(by_cat.get("tourist_poi", 0) + by_cat.get("event_venue", 0)),
        "n_competidores": float(by_cat.get("competitor", 0)),
        "n_anclas": float(by_cat.get("ancla", 0)),
    }


def actualizar_scores_poi(ubicacion_id: str) -> int:
    """
    Recalcula n_* desde puntos_interes y actualiza el snapshot conservando el resto de features.
    Llamar tras cualquier sync de POIs (Google Places, Esri Places, manual).
    """
    from src.data_processing.geo_enrichment import get_geo_vals, ingestar_snapshot

    current = get_geo_vals(ubicacion_id)
    if not current:
        return 0
    merged = {**current, **calcular_scores_poi(ubicacion_id)}
    n = ingestar_snapshot(ubicacion_id, merged)
    log.info("[%s] scores POI actualizados — %d features", ubicacion_id, n)
    return n


def ingestar_snapshot_esri(
    ubicacion_id: str,
    valores: dict[str, float | None],
) -> int:
    """
    Reemplaza el snapshot geo de la ubicación con los valores de GeoEnrichment.
    Borra lo anterior y escribe lo nuevo. Cadencia mensual.

    valores: {señal_id: valor_numérico | None}  — claves según GEO_FEATURE_COLS.
    Devuelve el número de features insertadas.
    """
    from src.data_processing.geo_enrichment import ingestar_snapshot

    poi_scores = calcular_scores_poi(ubicacion_id)
    todos = {**valores, **poi_scores}

    n = ingestar_snapshot(ubicacion_id, todos)
    log.info("[%s] geo snapshot actualizado — %d features", ubicacion_id, n)
    return n
