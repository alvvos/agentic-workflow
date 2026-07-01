from __future__ import annotations

import json

from src.api.modelos.fuente import ConfigFuente, FuenteDisponible
from src.db.store import get_conn


def _cargar_catalogo() -> dict[str, FuenteDisponible]:
    rows = (
        get_conn()
        .execute(
            "SELECT fuente, categoria, periodicidad, descripcion, url_referencia, "
            "cobertura_desde, latencia_dias, paises, params_schema, params_ejemplo "
            "FROM fuentes WHERE activo = TRUE ORDER BY fuente"
        )
        .fetchall()
    )
    catalogo: dict[str, FuenteDisponible] = {}
    for r in rows:
        catalogo[r[0]] = FuenteDisponible(
            source=r[0],
            categoria=r[1],
            periodicidad=r[2],
            descripcion=r[3],
            url_referencia=r[4],
            cobertura_desde=r[5],
            latencia_dias=r[6],
            paises=r[7] if isinstance(r[7], list) else [],
            params_schema=r[8],
            params_ejemplo=r[9] if isinstance(r[9], dict) else {},
        )
    return catalogo


def catalogo_fuentes() -> list[FuenteDisponible]:
    return list(_cargar_catalogo().values())


def listar_fuentes(location_uuid: str) -> list[ConfigFuente]:
    rows = (
        get_conn()
        .execute(
            "SELECT id, ubicacion_id, fuente, params, activo "
            "FROM config_fuentes "
            "WHERE ubicacion_id = ? "
            "ORDER BY fuente",
            [location_uuid],
        )
        .fetchall()
    )
    return [
        ConfigFuente(
            id=r[0],
            location_uuid=r[1],
            source=r[2],
            params=r[3] if isinstance(r[3], dict) else {},
            activo=r[4],
        )
        for r in rows
    ]


def configurar_fuente(
    location_uuid: str,
    source: str,
    params: dict,
) -> tuple[ConfigFuente | None, str | None]:
    """
    Inserta o actualiza la configuración de una fuente para una ubicación.
    Devuelve (ConfigFuente, None) si OK o (None, mensaje_error) si el source no existe.
    """
    if not params:
        return None, "params no puede estar vacío"
    catalogo = {f.source for f in catalogo_fuentes()}
    if source not in catalogo:
        return None, f"source '{source}' no reconocido — consulta GET /fuentes/catalogo"

    conn = get_conn()
    conn.execute(
        "INSERT INTO config_fuentes (ubicacion_id, fuente, params, activo) "
        "VALUES (?, ?, ?::jsonb, TRUE) "
        "ON CONFLICT (ubicacion_id, fuente) "
        "DO UPDATE SET params = EXCLUDED.params, activo = TRUE",
        [location_uuid, source, json.dumps(params, ensure_ascii=False)],
    )
    row = conn.execute(
        "SELECT id, ubicacion_id, fuente, params, activo "
        "FROM config_fuentes "
        "WHERE ubicacion_id = ? AND fuente = ?",
        [location_uuid, source],
    ).fetchone()
    return (
        ConfigFuente(
            id=row[0],
            location_uuid=row[1],
            source=row[2],
            params=row[3] if isinstance(row[3], dict) else {},
            activo=row[4],
        ),
        None,
    )


def eliminar_fuente(location_uuid: str, source: str) -> bool:
    """Desactiva la fuente (activo = FALSE). Devuelve False si no existía."""
    conn = get_conn()
    row_antes = conn.execute(
        "SELECT id FROM config_fuentes " "WHERE ubicacion_id = ? AND fuente = ? AND activo = TRUE",
        [location_uuid, source],
    ).fetchone()
    if row_antes is None:
        return False
    conn.execute(
        "UPDATE config_fuentes SET activo = FALSE " "WHERE ubicacion_id = ? AND fuente = ?",
        [location_uuid, source],
    )
    return True
