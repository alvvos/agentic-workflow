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
    "use_replicated": ["eoh_viajeros_total", "eoh_pernoctaciones_total"],
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


def _parse_year_month(fecha_str: str) -> tuple[int, int] | None:
    """Extrae (year, month) de la cadena ISO devuelta por la API del INE."""
    try:
        # Formato: "2026-07-01T00:00:00.000+02:00"
        ts = fecha_str[:10]  # "2026-07-01"
        year, month, _ = ts.split("-")
        return int(year), int(month)
    except Exception:
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
            fecha_str = punto.get("Fecha", "")
            valor = punto.get("Valor")
            if valor is None or valor == "":
                continue
            try:
                valor_f = float(valor)
            except (TypeError, ValueError):
                continue
            ym = _parse_year_month(fecha_str)
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
