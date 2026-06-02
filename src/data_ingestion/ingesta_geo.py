from datetime import date, timedelta

from src.data_processing.geo_enrichment import (
    GEO_FEATURE_COLS,
    GEO_FEATURES_BACKDATABLE,
    invalidate_geo_cache,
)

TRAINING_START = "2024-01-01"


def _conn():
    from src.db.store import get_conn
    return get_conn()


def ingestar_snapshot_esri(
    location_uuid: str,
    valores: dict,
    fecha_entrega: str = None,
) -> dict:
    """
    Registra una nueva entrega de datos Esri para una ubicación en store_geo_snapshots.

    Primera entrega
    ───────────────
    Crea dos grupos de filas:
    1. [TRAINING_START → fecha_entrega-1] con solo features backdatables (AIS estructurales).
    2. [fecha_entrega → abierto] con todas las features disponibles.

    Entregas subsiguientes
    ──────────────────────
    Cierra el snapshot activo y abre uno nuevo. El histórico es inmutable.

    catchment_rings se ignora silenciosamente (pendiente migración a tabla de geometrías).
    """
    if fecha_entrega is None:
        fecha_entrega = date.today().isoformat()

    # catchment_rings no es una feature escalar — ignorar silenciosamente
    valores.pop("_catchment_rings", None)

    desconocidas = set(valores.keys()) - set(GEO_FEATURE_COLS)
    if desconocidas:
        raise ValueError(f"Features no reconocidas: {desconocidas}")

    conn = _conn()
    fecha_entrega_dt = date.fromisoformat(fecha_entrega)
    cierre_anterior  = (fecha_entrega_dt - timedelta(days=1)).isoformat()

    # ── ¿Primera entrega? ────────────────────────────────────────────────────
    n_con_dato = conn.execute(
        "SELECT COUNT(*) FROM store_geo_snapshots WHERE location_uuid = ? AND value IS NOT NULL",
        [location_uuid],
    ).fetchone()[0]
    is_primera_entrega = (n_con_dato == 0)

    nuevos_snapshots_log = []
    politica_log = []

    if is_primera_entrega:
        # Verificar si ya existe el placeholder estructural
        tiene_placeholder = conn.execute(
            "SELECT COUNT(*) FROM store_geo_snapshots WHERE location_uuid = ? AND valid_from = ?",
            [location_uuid, TRAINING_START],
        ).fetchone()[0] > 0

        backdated = [c for c in GEO_FEATURES_BACKDATABLE if valores.get(c) is not None]

        if tiene_placeholder:
            # Actualizar valores backdatables en el placeholder existente
            for col in backdated:
                conn.execute("""
                    UPDATE store_geo_snapshots
                    SET value = ?, valid_to = ?
                    WHERE location_uuid = ? AND valid_from = ? AND feature_key = ?
                """, [float(valores[col]), cierre_anterior, location_uuid, TRAINING_START, col])
            # Cerrar features que aún no tenían valid_to
            conn.execute("""
                UPDATE store_geo_snapshots
                SET valid_to = ?
                WHERE location_uuid = ? AND valid_from = ? AND valid_to IS NULL
            """, [cierre_anterior, location_uuid, TRAINING_START])
        else:
            # Insertar snapshot estructural backdated
            rows_backdated = [
                (location_uuid, col, TRAINING_START,
                 float(valores[col]) if valores.get(col) is not None else None,
                 cierre_anterior)
                for col in GEO_FEATURES_BACKDATABLE
            ]
            conn.executemany(
                "INSERT INTO store_geo_snapshots (location_uuid, feature_key, valid_from, value, valid_to) "
                "VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                rows_backdated,
            )

        nuevos_snapshots_log.append(1)
        politica_log.append({
            "tipo": "estructural_backdated",
            "valid_from": TRAINING_START,
            "valid_to": cierre_anterior,
            "features": backdated,
        })
    else:
        # Cerrar snapshot activo
        conn.execute(
            "UPDATE store_geo_snapshots SET valid_to = ? WHERE location_uuid = ? AND valid_to IS NULL",
            [cierre_anterior, location_uuid],
        )

    # ── Snapshot completo (fecha_entrega → abierto) ──────────────────────────
    features_con_dato = [c for c in GEO_FEATURE_COLS if valores.get(c) is not None]
    rows_nuevo = [
        (location_uuid, col, fecha_entrega,
         float(valores[col]) if valores.get(col) is not None else None,
         None)
        for col in GEO_FEATURE_COLS
    ]
    conn.executemany(
        "INSERT INTO store_geo_snapshots (location_uuid, feature_key, valid_from, value, valid_to) "
        "VALUES (?,?,?,?,?) ON CONFLICT (location_uuid, feature_key, valid_from) "
        "DO UPDATE SET value = excluded.value, valid_to = excluded.valid_to",
        rows_nuevo,
    )
    nuevos_snapshots_log.append(1)
    politica_log.append({
        "tipo": "completo" if is_primera_entrega else "actualizacion",
        "valid_from": fecha_entrega,
        "valid_to": None,
        "features": features_con_dato,
    })

    # Invalidar caché en memoria de geo_enrichment
    invalidate_geo_cache(location_uuid)

    # Invalidar modelo ML en caché para esta ubicación
    try:
        from src.services.ml_predictivo import invalidar_modelos_location
        invalidar_modelos_location(location_uuid)
    except Exception:
        pass

    return {
        "location_uuid":       location_uuid,
        "primera_entrega":     is_primera_entrega,
        "snapshots_creados":   sum(nuevos_snapshots_log),
        "features_registradas": features_con_dato,
        "politica_aplicada":   politica_log,
    }


def actualizar_catchment_rings(location_uuid: str, lat: float, lon: float) -> bool:
    """Pendiente: almacenamiento de geometrías en DB. Devuelve False por ahora."""
    return False


def listar_estado_geo() -> list[dict]:
    """Audit: qué locations tienen datos geo y cuántas features tienen valor."""
    conn = _conn()
    rows = conn.execute("""
        SELECT location_uuid,
               COUNT(CASE WHEN value IS NOT NULL THEN 1 END) AS features_con_dato,
               COUNT(*) AS features_total,
               MAX(valid_from) AS ultima_entrega
        FROM store_geo_snapshots
        WHERE valid_to IS NULL
        GROUP BY location_uuid
        ORDER BY features_con_dato DESC
    """).fetchall()
    return [
        {"location_uuid": r[0], "features_con_dato": r[1],
         "features_total": r[2], "ultima_entrega": str(r[3])}
        for r in rows
    ]
