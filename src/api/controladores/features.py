from __future__ import annotations

from src.api.modelos.feature import EstadoFeature, Feature
from src.db.store import get_conn


def listar_features_catalogo() -> list[Feature]:
    rows = (
        get_conn()
        .execute(
            "SELECT feature_key, source, categoria, status, "
            "label, sublabel, color, icon_cls, agg_fn, display_mode, "
            "canonical_type, fallback_feature_key "
            "FROM feature_registry "
            "ORDER BY feature_key"
        )
        .fetchall()
    )
    return [
        Feature(
            feature_key=r[0],
            source=r[1],
            categoria=r[2],
            status_registro=r[3],
            label=r[4],
            sublabel=r[5],
            color=r[6],
            icon_cls=r[7],
            agg_fn=r[8],
            display_mode=r[9],
            canonical_type=r[10],
            fallback_feature_key=r[11],
        )
        for r in rows
    ]


def listar_features(location_uuid: str) -> list[EstadoFeature]:
    rows = (
        get_conn()
        .execute(
            "SELECT feature_key, location_uuid, status, wmape_delta, periodicidad "
            "FROM feature_flags "
            "WHERE location_uuid = ? "
            "ORDER BY feature_key",
            [location_uuid],
        )
        .fetchall()
    )
    return [
        EstadoFeature(
            feature_key=r[0],
            location_uuid=r[1],
            status=r[2],
            wmape_delta=r[3],
            periodicidad=r[4],
        )
        for r in rows
    ]


def cambiar_estado_feature(
    location_uuid: str,
    feature_key: str,
    nuevo_status: str,
) -> EstadoFeature | None:
    conn = get_conn()
    existe = conn.execute(
        "SELECT 1 FROM feature_flags WHERE location_uuid = ? AND feature_key = ?",
        [location_uuid, feature_key],
    ).fetchone()
    if existe is None:
        return None
    conn.execute(
        "UPDATE feature_flags SET status = ? " "WHERE location_uuid = ? AND feature_key = ?",
        [nuevo_status, location_uuid, feature_key],
    )
    row = conn.execute(
        "SELECT feature_key, location_uuid, status, wmape_delta, periodicidad "
        "FROM feature_flags "
        "WHERE location_uuid = ? AND feature_key = ?",
        [location_uuid, feature_key],
    ).fetchone()
    return EstadoFeature(
        feature_key=row[0],
        location_uuid=row[1],
        status=row[2],
        wmape_delta=row[3],
        periodicidad=row[4],
    )
