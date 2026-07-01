from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

from src.api.modelos.fuente import ConfigFuente, FuenteDisponible
from src.db.store import get_conn

_CATALOGO: dict[str, FuenteDisponible] | None = None


def _cargar_catalogo() -> dict[str, FuenteDisponible]:
    catalogo: dict[str, FuenteDisponible] = {}
    for pkg_path in ("src.data_ingestion.mensual", "src.data_ingestion.diaria"):
        try:
            pkg = importlib.import_module(pkg_path)
            pkg_dir = Path(pkg.__file__).parent
        except Exception:
            continue
        for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
            if modname.startswith("_"):
                continue
            try:
                mod = importlib.import_module(f"{pkg_path}.{modname}")
                entry = getattr(mod, "CATALOG_ENTRY", None)
                source = getattr(mod, "SOURCE", None)
                paises = getattr(mod, "CATALOG_PAISES", [])
                if entry and source:
                    catalogo[source] = FuenteDisponible(
                        source=source,
                        categoria=entry.get("categoria"),
                        periodicidad=entry.get("periodicidad"),
                        descripcion=entry.get("descripcion"),
                        url_referencia=entry.get("url_referencia"),
                        cobertura_desde=entry.get("cobertura_desde"),
                        latencia_dias=entry.get("latencia_dias"),
                        paises=paises,
                        params_schema=entry.get("params_schema"),
                        params_ejemplo=entry.get("params_ejemplo"),
                    )
            except Exception:
                pass
    return catalogo


def catalogo_fuentes() -> list[FuenteDisponible]:
    global _CATALOGO
    if _CATALOGO is None:
        _CATALOGO = _cargar_catalogo()
    return list(_CATALOGO.values())


def listar_fuentes(location_uuid: str) -> list[ConfigFuente]:
    rows = (
        get_conn()
        .execute(
            "SELECT id, location_uuid, source, params, activo "
            "FROM location_source_config "
            "WHERE location_uuid = ? "
            "ORDER BY source",
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
        "INSERT INTO location_source_config (location_uuid, source, params, activo) "
        "VALUES (?, ?, ?::jsonb, TRUE) "
        "ON CONFLICT (location_uuid, source) "
        "DO UPDATE SET params = EXCLUDED.params, activo = TRUE",
        [location_uuid, source, json.dumps(params, ensure_ascii=False)],
    )
    row = conn.execute(
        "SELECT id, location_uuid, source, params, activo "
        "FROM location_source_config "
        "WHERE location_uuid = ? AND source = ?",
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
        "SELECT id FROM location_source_config "
        "WHERE location_uuid = ? AND source = ? AND activo = TRUE",
        [location_uuid, source],
    ).fetchone()
    if row_antes is None:
        return False
    conn.execute(
        "UPDATE location_source_config SET activo = FALSE "
        "WHERE location_uuid = ? AND source = ?",
        [location_uuid, source],
    )
    return True
