"""
Geoespacial Esri — gestión de snapshots en snapshots_geo.

A diferencia del resto de prefetch, geo no hace fetch HTTP automático.
Los datos llegan de Esri y se ingresan via ingestar_snapshot_esri().

run() devuelve el estado actual de features geo por location (auditoría).

CLI:
    python -m src.data_ingestion.geo                  # estado de todas
    python -m src.data_ingestion.geo --location UUID  # solo una
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_processing.geo_enrichment import (
    GEO_FEATURE_COLS,
    GEO_FEATURES_BACKDATABLE,
    invalidate_geo_cache,
)

_TRAINING_START = "2024-01-01"


def _conn():
    from src.db.store import get_conn

    return get_conn()


# ── Ingesta de snapshot Esri ──────────────────────────────────────────────────


def ingestar_snapshot_esri(
    location_uuid: str,
    valores: dict,
    fecha_entrega: str | None = None,
) -> dict:
    """
    Registra una entrega de datos Esri en snapshots_geo.

    Primera entrega:
      1. [TRAINING_START → fecha_entrega-1] solo features backdatables (AIS estructurales).
      2. [fecha_entrega → abierto] todas las features disponibles.

    Entregas subsiguientes:
      Cierra el snapshot activo y abre uno nuevo. El histórico es inmutable.

    catchment_rings en valores['_catchment_rings'] se persiste en ubicaciones
    y se elimina del dict antes de procesar features escalares.
    """
    if fecha_entrega is None:
        fecha_entrega = date.today().isoformat()

    catchment_rings = valores.pop("_catchment_rings", None)

    desconocidas = set(valores.keys()) - set(GEO_FEATURE_COLS)
    if desconocidas:
        raise ValueError(f"Features no reconocidas: {desconocidas}")

    conn = _conn()
    fecha_entrega_dt = date.fromisoformat(fecha_entrega)
    cierre_anterior = (fecha_entrega_dt - timedelta(days=1)).isoformat()

    n_con_dato = conn.execute(
        "SELECT COUNT(*) FROM snapshots_geo WHERE ubicacion_id = ? AND valor IS NOT NULL",
        [location_uuid],
    ).fetchone()[0]
    is_primera = n_con_dato == 0

    politica_log: list[dict] = []

    if is_primera:
        tiene_placeholder = (
            conn.execute(
                "SELECT COUNT(*) FROM snapshots_geo WHERE ubicacion_id = ? AND vigente_desde = ?",
                [location_uuid, _TRAINING_START],
            ).fetchone()[0]
            > 0
        )

        backdated = [c for c in GEO_FEATURES_BACKDATABLE if valores.get(c) is not None]

        if tiene_placeholder:
            for col in backdated:
                conn.execute(
                    """
                    UPDATE snapshots_geo
                    SET valor = ?, vigente_hasta = ?
                    WHERE ubicacion_id = ? AND vigente_desde = ? AND señal_id = ?
                """,
                    [float(valores[col]), cierre_anterior, location_uuid, _TRAINING_START, col],
                )
            conn.execute(
                """
                UPDATE snapshots_geo SET vigente_hasta = ?
                WHERE ubicacion_id = ? AND vigente_desde = ? AND vigente_hasta IS NULL
            """,
                [cierre_anterior, location_uuid, _TRAINING_START],
            )
        else:
            conn.executemany(
                "INSERT INTO snapshots_geo "
                "(ubicacion_id, señal_id, vigente_desde, valor, vigente_hasta) "
                "VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                [
                    (
                        location_uuid,
                        col,
                        _TRAINING_START,
                        float(valores[col]) if valores.get(col) is not None else None,
                        cierre_anterior,
                    )
                    for col in GEO_FEATURES_BACKDATABLE
                ],
            )

        politica_log.append(
            {
                "tipo": "estructural_backdated",
                "vigente_desde": _TRAINING_START,
                "vigente_hasta": cierre_anterior,
                "features": backdated,
            }
        )
    else:
        conn.execute(
            "UPDATE snapshots_geo SET vigente_hasta = ? WHERE ubicacion_id = ? AND vigente_hasta IS NULL",
            [cierre_anterior, location_uuid],
        )

    features_con_dato = [c for c in GEO_FEATURE_COLS if valores.get(c) is not None]
    conn.executemany(
        "INSERT INTO snapshots_geo "
        "(ubicacion_id, señal_id, vigente_desde, valor, vigente_hasta) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT (ubicacion_id, señal_id, vigente_desde) "
        "DO UPDATE SET valor = excluded.value, vigente_hasta = excluded.vigente_hasta",
        [
            (
                location_uuid,
                col,
                fecha_entrega,
                float(valores[col]) if valores.get(col) is not None else None,
                None,
            )
            for col in GEO_FEATURE_COLS
        ],
    )

    politica_log.append(
        {
            "tipo": "completo" if is_primera else "actualizacion",
            "vigente_desde": fecha_entrega,
            "vigente_hasta": None,
            "features": features_con_dato,
        }
    )

    if catchment_rings:
        actualizar_catchment_rings(location_uuid, catchment_rings)

    invalidate_geo_cache(location_uuid)

    try:
        from src.services.ml_predictivo import invalidar_modelos_location

        invalidar_modelos_location(location_uuid)
    except Exception:
        pass

    return {
        "location_uuid": location_uuid,
        "primera_entrega": is_primera,
        "features_registradas": features_con_dato,
        "politica_aplicada": politica_log,
    }


def actualizar_catchment_rings(location_uuid: str, rings: list) -> bool:
    """Guarda las isócronas peatonales en ubicaciones.catchment_rings_json."""
    import json

    if not rings:
        return False
    try:
        _conn().execute(
            "UPDATE ubicaciones SET catchment_rings_json = ? WHERE ubicacion_id = ?",
            [json.dumps(rings), location_uuid],
        )
        return True
    except Exception:
        return False


# ── Estado / auditoría ────────────────────────────────────────────────────────


def listar_estado(verbose: bool = True) -> list[dict]:
    """
    Devuelve para cada location: cuántas features tienen valor en el snapshot activo.
    """
    rows = (
        _conn()
        .execute(
            """
        SELECT ubicacion_id,
               COUNT(CASE WHEN valor IS NOT NULL THEN 1 END) AS features_con_dato,
               COUNT(*)                                      AS features_total,
               MAX(vigente_desde)                               AS ultima_entrega
        FROM   snapshots_geo
        WHERE  vigente_hasta IS NULL
        GROUP  BY ubicacion_id
        ORDER  BY features_con_dato DESC
    """
        )
        .fetchall()
    )

    result = [
        {
            "location_uuid": r[0],
            "features_con_dato": r[1],
            "features_total": r[2],
            "ultima_entrega": str(r[3]),
        }
        for r in rows
    ]

    if verbose:
        print(f"\n{'─'*56}")
        print(f"  Estado geo — {len(result)} location(s) con snapshots activos")
        print(f"{'─'*56}")
        for r in result:
            bar = "█" * r["features_con_dato"] + "░" * (
                r["features_total"] - r["features_con_dato"]
            )
            print(
                f"  {r['location_uuid'][:8]}  {bar}  "
                f"{r['features_con_dato']}/{r['features_total']}  "
                f"última: {r['ultima_entrega']}"
            )
        print(f"{'─'*56}\n")

    return result


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,  # no aplica (sin HTTP); mantenido por convención
    verbose: bool = True,
) -> dict[str, int]:
    """
    Devuelve el estado de features geo por location {uuid: n_features_con_dato}.
    No hace fetch HTTP; geo requiere entrega manual via ingestar_snapshot_esri().
    """
    rows = (
        _conn()
        .execute(
            """
        SELECT ubicacion_id,
               COUNT(CASE WHEN valor IS NOT NULL THEN 1 END) AS n
        FROM   snapshots_geo
        WHERE  vigente_hasta IS NULL
          AND  (? IS NULL OR ubicacion_id = ?)
        GROUP  BY ubicacion_id
        """,
            [location_uuid, location_uuid],
        )
        .fetchall()
    )

    stats = {r[0]: r[1] for r in rows}

    if verbose:
        listar_estado(verbose=True)

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from src.data_ingestion._common import make_parser

    parser = make_parser("geoespacial Esri (auditoría de snapshots_geo)")
    # max-age y force no aplican, pero se incluyen por convención
    args = parser.parse_args()
    run(location_uuid=args.location, verbose=not args.quiet)
