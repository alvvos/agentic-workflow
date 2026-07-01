"""
Conector para series estadísticas del INE (JSON API tempus3).
Usado actualmente para la Encuesta de Ocupación Hotelera (EOH).

Interfaz pública:
    TIPO = "series_estadisticas"
    sync(ubicacion_id, cfg, verbose) -> int
"""

from __future__ import annotations

import requests

from src.data_ingestion._common import ensure_feature_registry, write_month_uniform

TIPO = "series_estadisticas"

_TIMEOUT = 30


def sync(ubicacion_id: str, cfg: dict, verbose: bool = True) -> int:
    """
    Descarga y persiste viajeros y pernoctaciones hoteleras del INE.

    ubicacion_id: UUID de la ubicación.
    cfg: config efectiva — debe contener provincia_nombre y base_url.
    No llama a is_fresh() ni write_sync_marker() — los gestiona el orquestador.
    Devuelve el número de filas escritas.
    """
    provincia = cfg.get("provincia_nombre")
    if not provincia:
        if verbose:
            print(f"  [series_estadisticas] {ubicacion_id}: sin provincia_nombre en cfg — omitido")
        return 0

    base_url = cfg.get("base_url", "https://servicios.ine.es/wstempus/js/ES")
    tabla_viajeros_default = cfg.get("tabla_viajeros", 2078)
    feature_key_viajeros = cfg.get("feature_key_viajeros", "ine_viajeros_hoteleros")
    feature_key_pernoctaciones = cfg.get(
        "feature_key_pernoctaciones", "ine_pernoctaciones_hoteleras"
    )

    def _fetch_tabla(tabla_id: int, nult: int = 300) -> list[dict]:
        url = f"{base_url}/DATOS_TABLA/{tabla_id}?nult={nult}"
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _parse_serie_mensual(serie: dict) -> list[tuple[int, int, float]]:
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
        must_contain: list[str],
        must_not: list[str] | None = None,
    ) -> list[dict]:
        must_not = must_not or []
        matches = []
        for serie in raw:
            nombre = serie.get("Nombre", "").lower()
            if provincia.lower() not in nombre:
                continue
            if not all(t.lower() in nombre for t in must_contain):
                continue
            if any(t.lower() in nombre for t in must_not):
                continue
            matches.append(serie)
        return matches

    tabla_v = int(cfg.get("tabla_viajeros", tabla_viajeros_default))
    tabla_p = int(cfg.get("tabla_pernoctaciones", tabla_viajeros_default))
    total = 0

    raw_v = _fetch_tabla(tabla_v)
    series_v = _find_series(raw_v, must_contain=["viajero"])
    if not series_v:
        if verbose:
            print(
                f"  [series_estadisticas] viajeros: ninguna serie para '{provincia}' en tabla {tabla_v}"
            )
    else:
        agg: dict[tuple[int, int], float] = {}
        for s in series_v:
            for yr, mes, val in _parse_serie_mensual(s):
                agg[(yr, mes)] = agg.get((yr, mes), 0.0) + val
        series_total = _find_series(raw_v, must_contain=["viajero", "total"])
        if series_total:
            agg = {}
            for s in series_total:
                for yr, mes, val in _parse_serie_mensual(s):
                    agg[(yr, mes)] = val

        ensure_feature_registry(
            feature_key_viajeros,
            "ine_eoh",
            "turismo",
            f"Viajeros hoteleros estimados — {provincia} (INE EOH)",
        )
        for (yr, mes), val in sorted(agg.items()):
            total += write_month_uniform(yr, mes, val, ubicacion_id, feature_key_viajeros, verbose)

    raw_p = _fetch_tabla(tabla_p) if tabla_p != tabla_v else raw_v
    series_p = _find_series(raw_p, must_contain=["pernoctaci"])
    series_p_total = _find_series(raw_p, must_contain=["pernoctaci", "total"])
    if series_p_total:
        series_p = series_p_total

    if not series_p:
        if verbose:
            print(
                f"  [series_estadisticas] pernoctaciones: ninguna serie para '{provincia}' en tabla {tabla_p}"
            )
    else:
        agg_p: dict[tuple[int, int], float] = {}
        for s in series_p:
            for yr, mes, val in _parse_serie_mensual(s):
                agg_p[(yr, mes)] = val

        ensure_feature_registry(
            feature_key_pernoctaciones,
            "ine_eoh",
            "turismo",
            f"Pernoctaciones hoteleras estimadas — {provincia} (INE EOH)",
        )
        for (yr, mes), val in sorted(agg_p.items()):
            total += write_month_uniform(
                yr, mes, val, ubicacion_id, feature_key_pernoctaciones, verbose
            )

    return total
