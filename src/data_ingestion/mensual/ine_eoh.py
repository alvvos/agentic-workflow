"""
INE — Encuesta de Ocupación Hotelera (EOH).

Fuente: API JSON tempus del INE.
  Base: https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/{tabla_id}
  Listado de tablas EOH: https://servicios.ine.es/wstempus/js/ES/TABLAS_OPERACION/EOH

Tablas usadas por defecto:
  2078 — Viajeros y pernoctaciones estimados, por provincias (mensual, hoteleros)
         Cobertura desde 1999. Lag ~45 días. Granularidad: provincia.

Para municipio capital (ej. Madrid ciudad en vez de provincia):
  Buscar en TABLAS_OPERACION/EOH tablas con "municipio" o "capital".

Configuración en location_source_config (source = 'ine_eoh'):
  {
    "tabla_viajeros":       2078,       # ID tabla INE para viajeros
    "tabla_pernoctaciones": 2078,       # ID tabla INE para pernoctaciones (a veces = viajeros)
    "provincia_nombre":     "Madrid",   # fragmento del nombre de serie que identifica la provincia
    "municipio_codigo":     "28079"     # código INE municipio (opcional, para filtro futuro)
  }

Feature keys escritas:
  ine_viajeros_hoteleros      — viajeros estimados en establecimientos hoteleros (mensual)
  ine_pernoctaciones_hoteleras — pernoctaciones estimadas (mensual)

Escribe en store_features_ext con periodicidad mensual distribuida en días.

CLI:
    python -m src.data_ingestion.mensual.ine_eoh
    python -m src.data_ingestion.mensual.ine_eoh --list-series --tabla 2078
    python -m src.data_ingestion.mensual.ine_eoh --force
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.diaria._common import is_fresh, write_sync_marker
from src.data_ingestion.mensual._common import (
    ensure_feature_registry,
    get_configured_locations,
    write_month_uniform,
)

# ── Declaraciones de paquete mensual ─────────────────────────────────────────

SOURCE = "ine_eoh"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "ine_viajeros_hoteleros",
    "source": SOURCE,
    "categoria": "turismo",
    "periodicidad": "mensual",
    "descripcion": (
        "Viajeros y pernoctaciones en establecimientos hoteleros — INE Encuesta de "
        "Ocupación Hotelera (EOH). Mide el volumen de turistas alojados en la provincia "
        "o municipio de la ubicación. Proxy directo del componente turístico del tráfico "
        "retail en zonas con alta afluencia de visitantes (centros urbanos, zonas costeras)."
    ),
    "url_referencia": "https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736177015",
    "granularidad": "provincia o municipio (mensual, distribuida en días)",
    "cobertura_desde": "1999-01",
    "latencia_dias": 45,
    "notas_tecnicas": (
        "Requiere configurar 'provincia_nombre' en location_source_config con el "
        "fragmento del nombre de la serie INE que identifica la provincia "
        "(ej. 'Madrid', 'Málaga', 'Barcelona'). "
        "Tabla por defecto: 2078 (viajeros+pernoctaciones por provincias). "
        "Para datos de municipio capital usar tabla específica de la operación EOH."
    ),
    "params_schema": (
        "{'provincia_nombre': '<fragmento exacto del nombre de provincia en series INE — "
        "ej. Madrid, Málaga, Barcelona, Valencia, Sevilla, Alicante, Baleares>', "
        "'tabla_viajeros': <int, opcional, default 2078>, "
        "'municipio_codigo': '<código INE municipio, opcional>'}."
    ),
    "params_ejemplo": {"provincia_nombre": "Málaga"},
}

_BASE = "https://servicios.ine.es/wstempus/js/ES"
_TIMEOUT = 30
_DEFAULT_TABLA_VIAJEROS = 2078
_DEFAULT_TABLA_PERNOCTACIONES = 2078

_FK_VIAJEROS = "ine_viajeros_hoteleros"
_FK_PERNOCTACIONES = "ine_pernoctaciones_hoteleras"


# ── Config desde location_source_config ──────────────────────────────────────


def _get_configured_locations() -> list[tuple[str, dict]]:
    return [(lu, p) for lu, p in get_configured_locations(SOURCE) if p.get("provincia_nombre")]


# ── INE API helpers ───────────────────────────────────────────────────────────


def _fetch_tabla(tabla_id: int, nult: int = 300) -> list[dict]:
    url = f"{_BASE}/DATOS_TABLA/{tabla_id}?nult={nult}"
    r = requests.get(url, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _parse_serie_mensual(serie: dict) -> list[tuple[int, int, float]]:
    """Devuelve [(year, mes, value), ...] de una serie INE."""
    rows = []
    for dp in serie.get("Data", []):
        if dp.get("Secreto") or dp.get("Valor") is None:
            continue
        try:
            year = int(dp["Anyo"])
            periodo = dp.get("FK_Periodo") or dp.get("Periodo", "")
            if isinstance(periodo, int):
                mes = periodo
            else:
                mes = int(str(periodo).replace("M", ""))
            if not (1 <= mes <= 12):
                continue
            rows.append((year, mes, float(dp["Valor"])))
        except (KeyError, ValueError, TypeError):
            continue
    return rows


def _find_series(
    raw: list[dict],
    provincia_nombre: str,
    must_contain: list[str],
    must_not: list[str] | None = None,
) -> list[dict]:
    """Filtra las series que mencionan la provincia y los términos indicados."""
    must_not = must_not or []
    matches = []
    for serie in raw:
        nombre = serie.get("Nombre", "").lower()
        if provincia_nombre.lower() not in nombre:
            continue
        if not all(t.lower() in nombre for t in must_contain):
            continue
        if any(t.lower() in nombre for t in must_not):
            continue
        matches.append(serie)
    return matches


# ── Escritura en DB ───────────────────────────────────────────────────────────


# ── Sync principal ────────────────────────────────────────────────────────────


def sync_location(
    location_uuid: str,
    params: dict,
    verbose: bool = True,
) -> int:
    provincia = params["provincia_nombre"]
    tabla_v = int(params.get("tabla_viajeros", _DEFAULT_TABLA_VIAJEROS))
    tabla_p = int(params.get("tabla_pernoctaciones", _DEFAULT_TABLA_PERNOCTACIONES))

    total = 0

    # ── Viajeros ──────────────────────────────────────────────────────────────
    try:
        raw_v = _fetch_tabla(tabla_v)
        series_v = _find_series(raw_v, provincia, must_contain=["viajero"])
        if not series_v and verbose:
            print(
                f"  [ine_eoh] viajeros: ninguna serie encontrada para '{provincia}' en tabla {tabla_v}"
            )
        else:
            # Agregar todas las series coincidentes (residentes + extranjeros → total estimado)
            agg: dict[tuple[int, int], float] = {}
            for s in series_v:
                for yr, mes, val in _parse_serie_mensual(s):
                    agg[(yr, mes)] = agg.get((yr, mes), 0.0) + val
            # Si hay más de una serie, el total ya está en una de ellas (buscar "total")
            series_total = _find_series(raw_v, provincia, must_contain=["viajero", "total"])
            if series_total:
                agg = {}
                for s in series_total:
                    for yr, mes, val in _parse_serie_mensual(s):
                        agg[(yr, mes)] = val  # total directo

            ensure_feature_registry(
                _FK_VIAJEROS,
                SOURCE,
                "turismo",
                f"Viajeros hoteleros estimados — {provincia} (INE EOH)",
            )
            for (yr, mes), val in sorted(agg.items()):
                total += write_month_uniform(yr, mes, val, location_uuid, _FK_VIAJEROS, verbose)
    except Exception as e:
        if verbose:
            print(f"  [ine_eoh] viajeros ERROR — {e}")

    # ── Pernoctaciones ────────────────────────────────────────────────────────
    try:
        raw_p = _fetch_tabla(tabla_p) if tabla_p != tabla_v else raw_v
        series_p = _find_series(raw_p, provincia, must_contain=["pernoctaci"])
        series_p_total = _find_series(raw_p, provincia, must_contain=["pernoctaci", "total"])
        if series_p_total:
            series_p = series_p_total

        if not series_p and verbose:
            print(
                f"  [ine_eoh] pernoctaciones: ninguna serie para '{provincia}' en tabla {tabla_p}"
            )
        else:
            agg_p: dict[tuple[int, int], float] = {}
            for s in series_p:
                for yr, mes, val in _parse_serie_mensual(s):
                    agg_p[(yr, mes)] = val

            ensure_feature_registry(
                _FK_PERNOCTACIONES,
                SOURCE,
                "turismo",
                f"Pernoctaciones hoteleras estimadas — {provincia} (INE EOH)",
            )
            for (yr, mes), val in sorted(agg_p.items()):
                total += write_month_uniform(
                    yr, mes, val, location_uuid, _FK_PERNOCTACIONES, verbose
                )
    except Exception as e:
        if verbose:
            print(f"  [ine_eoh] pernoctaciones ERROR — {e}")

    return total


def sync(jobs: list, fecha: date) -> int:
    """Interfaz estándar para sync_mensual."""
    locations = _get_configured_locations()
    total = 0
    for loc_uuid, params in locations:
        total += sync_location(loc_uuid, params, verbose=True)
    return total


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 168,
    verbose: bool = True,
) -> dict[str, int]:
    """Interfaz nightly. Dato mensual → actualización semanal es suficiente."""
    locations = _get_configured_locations()
    if location_uuid is not None:
        locations = [(lu, p) for lu, p in locations if lu == location_uuid]

    result: dict[str, int] = {}
    for loc_uuid, params in locations:
        if is_fresh(loc_uuid, SOURCE, max_age_hours):
            result[loc_uuid] = 0
            continue
        try:
            n = sync_location(loc_uuid, params, verbose)
            write_sync_marker(loc_uuid, SOURCE)
            result[loc_uuid] = n
        except Exception as e:
            if verbose:
                print(f"  [ine_eoh] {loc_uuid} ERROR — {e}")
            result[loc_uuid] = 0

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingestor INE Encuesta Ocupación Hotelera")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--list-series", action="store_true", help="Lista todas las series de la tabla y sale"
    )
    parser.add_argument("--tabla", type=int, default=_DEFAULT_TABLA_VIAJEROS)
    parser.add_argument(
        "--provincia", type=str, default=None, help="Filtrar series por nombre de provincia"
    )
    args = parser.parse_args()

    if args.list_series:
        raw = _fetch_tabla(args.tabla, nult=1)
        for i, s in enumerate(raw):
            nombre = s.get("Nombre", "")
            if args.provincia is None or args.provincia.lower() in nombre.lower():
                print(f"  [{i:3d}] {nombre}")
        sys.exit(0)

    locations = _get_configured_locations()
    if not locations:
        print("[ine_eoh] No hay ubicaciones configuradas en location_source_config.")
        sys.exit(0)

    for loc_uuid, params in locations:
        sync_location(loc_uuid, params, verbose=True)
