"""
Sincronizacion mensual de senales de contexto — orquestador puro.

Lee la tabla `fuentes` para descubrir qué fuentes están activas con periodicidad
mensual, carga el conector correspondiente desde src/conectores/<tipo_conector>.py
y ejecuta sync() por cada ubicación configurada en config_fuentes.

CLI:
  python -m src.data_ingestion.sync_mensual
  python -m src.data_ingestion.sync_mensual --location <uuid>
  python -m src.data_ingestion.sync_mensual --solo metro_madrid
  python -m src.data_ingestion.sync_mensual --force
"""

from __future__ import annotations

import importlib

from src.data_ingestion._common import (
    get_configured_locations,
    get_source_config,
    is_fresh,
    write_sync_marker,
)


def _cargar_conector(tipo: str):
    return importlib.import_module(f"src.conectores.{tipo}")


def sync_all(
    location_uuid: str | None = None,
    max_age_hours: float = 168,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """
    Para cada fuente mensual activa en la DB:
      1. Carga el conector dinámicamente por tipo_conector.
      2. Ejecuta sync() solo para ubicaciones con config activa en config_fuentes.
      3. Escribe sync marker después de cada ejecución exitosa.

    Retorna {fuente: {ubicacion_id: n_rows}}.
    """
    from src.db.store import get_conn

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    fuentes_rows = (
        get_conn()
        .execute(
            "SELECT fuente, config FROM fuentes WHERE periodicidad = 'mensual' AND activo = TRUE"
        )
        .fetchall()
    )

    log(
        f"\n  sync_mensual/sync_all — {len(fuentes_rows)} fuente(s): "
        f"{', '.join(sorted(f for f, _ in fuentes_rows))}"
    )

    results: dict[str, dict[str, int]] = {}

    for fuente_nombre, config in sorted(fuentes_rows, key=lambda x: x[0]):
        tipo = config.get("tipo_conector") if config else None
        if not tipo:
            log(f"  [{fuente_nombre}] sin tipo_conector en config — omitido")
            continue
        try:
            conector = _cargar_conector(tipo)
        except ModuleNotFoundError:
            log(f"  [{fuente_nombre}] conector '{tipo}' no encontrado — omitido")
            continue

        configuradas = get_configured_locations(fuente_nombre)
        if location_uuid is not None:
            configuradas = [(lu, p) for lu, p in configuradas if lu == location_uuid]

        stats: dict[str, int] = {}
        for lu, params in configuradas:
            if is_fresh(lu, fuente_nombre, max_age_hours):
                stats[lu] = 0
                continue
            cfg = get_source_config(fuente_nombre, params)
            try:
                n = conector.sync(lu, cfg, verbose)
                write_sync_marker(lu, fuente_nombre)
                stats[lu] = n
            except Exception as e:
                log(f"  [!] {fuente_nombre}: {lu} ERROR — {e}")
                stats[lu] = 0

        results[fuente_nombre] = stats
        total = sum(stats.values()) if stats else 0
        log(f"  [{fuente_nombre}] {total} filas escritas")

    return results


def cargar_catalog(pais: str = "") -> list[dict]:
    """Devuelve entradas de catálogo de fuentes para context_scout.py."""
    from src.db.store import get_conn

    if pais:
        rows = (
            get_conn()
            .execute(
                "SELECT fuente, categoria, periodicidad, descripcion, url_referencia, "
                "cobertura_desde, latencia_dias, paises, esquema_params AS params_schema, ejemplo_params AS params_ejemplo, config "
                "FROM fuentes WHERE activo = TRUE "
                "AND (paises = '[]'::jsonb OR paises @> %s::jsonb)",
                [f'["{pais}"]'],
            )
            .fetchall()
        )
    else:
        rows = (
            get_conn()
            .execute(
                "SELECT fuente, categoria, periodicidad, descripcion, url_referencia, "
                "cobertura_desde, latencia_dias, paises, esquema_params AS params_schema, ejemplo_params AS params_ejemplo, config "
                "FROM fuentes WHERE activo = TRUE",
            )
            .fetchall()
        )
    cols = [
        "fuente",
        "categoria",
        "periodicidad",
        "descripcion",
        "url_referencia",
        "cobertura_desde",
        "latencia_dias",
        "paises",
        "params_schema",
        "params_ejemplo",
        "config",
    ]
    return [dict(zip(cols, r)) for r in rows]


def sync_esri_places_location(
    location_uuid: str,
    params: dict | None = None,
    verbose: bool = True,
) -> int:
    """
    Compatibilidad con src/callbacks/admin_pois.py.
    Delegado al conector pois_radio.
    """
    from src.conectores.pois_radio import sync_esri_places_location as _sync

    return _sync(location_uuid, params, verbose)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Sincronizacion mensual completa (todos los sources configurados)"
    )
    parser.add_argument("--location", metavar="UUID")
    parser.add_argument(
        "--solo",
        default=None,
        metavar="SOURCE[,SOURCE]",
        help="Ejecutar solo este source (ej: metro_madrid)",
    )
    parser.add_argument("--max-age", type=float, default=168, metavar="HORAS")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    only_set = set(args.solo.split(",")) if args.solo else None

    # Filtrar fuentes por --solo si se especificó
    if only_set:
        from src.db.store import get_conn as _get_conn

        _all = (
            _get_conn()
            .execute("SELECT fuente FROM fuentes WHERE periodicidad = 'mensual' AND activo = TRUE")
            .fetchall()
        )
        _active = {r[0] for r in _all} & only_set
        if not _active:
            print(f"[!] Ninguna de las fuentes {only_set} está activa.")
        else:
            sync_all(
                location_uuid=args.location,
                max_age_hours=0 if args.force else args.max_age,
                verbose=not args.quiet,
            )
    else:
        sync_all(
            location_uuid=args.location,
            max_age_hours=0 if args.force else args.max_age,
            verbose=not args.quiet,
        )
