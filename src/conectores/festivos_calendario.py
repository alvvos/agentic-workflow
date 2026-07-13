"""
Conector de festivos y vacaciones escolares — OpenHolidays API.

Interfaz pública:
    TIPO = "festivos_calendario"
    sync(ubicacion, cfg, verbose) -> int
"""

from __future__ import annotations

from datetime import date, timedelta

from src.data_ingestion._common import (
    EVENTS_DATE_FROM,
    EVENTS_HORIZON,
    write_calendario_org,
    write_ev_features,
)

TIPO = "festivos_calendario"


def sync(ubicacion: dict, cfg: dict, verbose: bool = True) -> int:  # noqa: ARG001
    """
    Descarga festivos regionales y vacaciones escolares para una ubicación.

    ubicacion: {ubicacion_id, nombre, lat, lon, pais_codigo, codigo_region, city}
    cfg: config efectiva de la fuente.
    No llama a is_fresh() ni write_sync_marker() — los gestiona el orquestador.
    Devuelve el número de días con datos escritos.
    """
    from src.data_processing.fuentes_eventos.open_holidays import (
        expand_periods,
        get_public_holidays_detail,
        get_school_holidays,
    )

    ubicacion_id = ubicacion["ubicacion_id"]
    nombre = ubicacion.get("nombre", ubicacion_id)
    pais_codigo = ubicacion["pais_codigo"]
    region_code = ubicacion["codigo_region"]
    date_from = EVENTS_DATE_FROM
    date_to = date.today() + timedelta(days=EVENTS_HORIZON)
    years = list(range(date_from.year, date_to.year + 1))

    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []

    def _slot(d: date) -> dict:
        if d not in daily:
            daily[d] = {"ev_vacaciones_escolares": 0, "ev_festivo_regional": 0}
        return daily[d]

    for year in years:
        for d in expand_periods(get_school_holidays(pais_codigo, year, region_code)):
            if date_from <= d <= date_to:
                _slot(d)["ev_vacaciones_escolares"] = 1
                raw_rows.append(
                    {
                        "evento_key": "vacaciones_escolares",
                        "fecha_inicio": d,
                        "fecha_fin": d,
                        "fuente": "open_holidays",
                        "source_key": f"oh_school:{pais_codigo}:{region_code or ''}:{d}",
                        "metadata": {"pais": pais_codigo, "region": region_code},
                    }
                )

        for fh in get_public_holidays_detail(pais_codigo, year, region_code):
            if not fh.get("nationwide", True) and date_from <= fh["fecha"] <= date_to:
                _slot(fh["fecha"])["ev_festivo_regional"] = 1
                raw_rows.append(
                    {
                        "evento_key": "festivo_regional",
                        "fecha_inicio": fh["fecha"],
                        "fecha_fin": fh["fecha"],
                        "fuente": "open_holidays",
                        "source_key": (
                            f"oh_ph:{pais_codigo}:{region_code or ''}:"
                            f"{fh['fecha']}:{fh['name']}"
                        ),
                        "metadata": {
                            "nombre": fh["name"],
                            "scope": fh.get("scope", ""),
                        },
                    }
                )

    write_ev_features(ubicacion_id, daily)
    write_calendario_org(ubicacion_id, raw_rows, pais_codigo)

    n = len(daily)
    if verbose:
        print(f"  [festivos_calendario] {nombre}: {n}d  (vacaciones + festivos regionales)")
    return n
