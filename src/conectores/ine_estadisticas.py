"""
Conector para la API Tempus3 del INE (Instituto Nacional de Estadística).

Descarga series de turismo (EOH, EGATUR) para señales de contexto mensual.

Interfaz pública:
    TIPO = "ine_estadisticas"
    sync(ubicacion_id, cfg, verbose) -> int

cfg esperada (defaults en _SOURCE_REGISTRY_SEED de store.py):
    {
        "series": {
            "EOT1763": "eoh_viajeros_total",
            "EOT1766": "eoh_pernoctaciones_total",
            "FREG520": "egatur_gasto_medio_diario",
        },
        "use_replicated": ["eoh_viajeros_total", "eoh_pernoctaciones_total"],
    }
"""

from __future__ import annotations

import requests

from src.data_ingestion._common import write_month_replicated, write_month_uniform

TIPO = "ine_estadisticas"

_BASE_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE"

_DEFAULT_CFG: dict = {
    "series": {
        "EOT1763": "eoh_viajeros_total",
        "EOT1766": "eoh_pernoctaciones_total",
        "FREG520": "egatur_gasto_medio_diario",
    },
    "use_replicated": [
        "eoh_viajeros_total",
        "eoh_pernoctaciones_total",
        "egatur_gasto_medio_diario",
    ],
}


# ── Fetch helpers ─────────────────────────────────────────────────────────────


def _fetch_serie(codigo: str, nult: int = 24) -> list[dict]:
    try:
        r = requests.get(
            f"{_BASE_URL}/{codigo}",
            params={"nult": nult},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("Data", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _extract_year_month(punto: dict) -> tuple[int, int] | None:
    """Extrae (year, month) de un data point de la API Tempus3 del INE.

    La API devuelve Fecha como Unix timestamp en ms, pero también incluye
    Anyo (año) y FK_Periodo (mes, 1-12) como campos estructurados fiables.
    """
    try:
        year = int(punto["Anyo"])
        month = int(punto["FK_Periodo"])
        if 1 <= month <= 12:
            return year, month
    except (KeyError, TypeError, ValueError):
        pass
    # Fallback: timestamp ms → date
    try:
        from datetime import datetime, timezone

        ts_ms = punto.get("Fecha")
        if ts_ms is not None:
            dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
            return dt.year, dt.month
    except Exception:
        pass
    return None


# ── Interfaz pública ──────────────────────────────────────────────────────────


def sync(ubicacion_id: str, cfg: dict, verbose: bool = True) -> int:
    """
    Descarga las series INE configuradas y persiste los valores mensuales.

    ubicacion_id: UUID de la ubicación.
    cfg: config efectiva (fusión de defaults + params de location).
    Devuelve el número de filas escritas.
    """
    effective_cfg = {**_DEFAULT_CFG, **cfg}
    series: dict[str, str] = effective_cfg.get("series", _DEFAULT_CFG["series"])
    use_replicated: list[str] = effective_cfg.get("use_replicated", _DEFAULT_CFG["use_replicated"])

    total_rows = 0

    for codigo, feature_key in series.items():
        data_points = _fetch_serie(codigo)
        if not data_points:
            if verbose:
                print(f"  [ine_estadisticas] {codigo} ({feature_key}): sin datos de la API")
            continue

        for punto in data_points:
            valor = punto.get("Valor")
            if valor is None or valor == "":
                continue
            try:
                valor_f = float(valor)
            except (TypeError, ValueError):
                continue
            ym = _extract_year_month(punto)
            if ym is None:
                continue
            year, month = ym

            if feature_key in use_replicated:
                n = write_month_replicated(
                    year, month, valor_f, ubicacion_id, feature_key, verbose=verbose
                )
            else:
                n = write_month_uniform(
                    year, month, valor_f, ubicacion_id, feature_key, verbose=verbose
                )
            total_rows += n

    if verbose:
        print(f"  [ine_estadisticas] {ubicacion_id}: {total_rows} filas escritas en total")
    return total_rows
