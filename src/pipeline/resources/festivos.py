"""
Recurso festivos — OpenHolidays API (vacaciones escolares + festivos regionales).

Configuración en fuentes.config:
  subdivisiones_es: dict   {region_code: subdivision_code} para España
  subdivisiones_mx: dict   {region_code: subdivision_code} para México

Interfaz pública: source(ubicaciones, cfg, date_from, date_to) -> dlt.Source
"""

from __future__ import annotations

from datetime import date, timedelta

import dlt
import requests

_BASE = "https://openholidaysapi.org"
_TIMEOUT = 15

_SUBDIV_ES_DEFAULT: dict[str, str] = {
    "AN": "ES-AN",
    "AR": "ES-AR",
    "AS": "ES-AS",
    "CB": "ES-CB",
    "CE": "ES-CE",
    "CL": "ES-CL",
    "CM": "ES-CM",
    "CN": "ES-CN",
    "CT": "ES-CT",
    "EX": "ES-EX",
    "GA": "ES-GA",
    "IB": "ES-IB",
    "MC": "ES-MC",
    "MD": "ES-MD",
    "ML": "ES-ML",
    "MU": "ES-MC",
    "NC": "ES-NC",
    "PV": "ES-PV",
    "RI": "ES-RI",
    "VC": "ES-VC",
}
_SUBDIV_MX_DEFAULT: dict[str, str] = {
    "CDMX": "MX-CMX",
    "JAL": "MX-JAL",
    "NL": "MX-NLE",
    "YUC": "MX-YUC",
    "NLE": "MX-NLE",
}


def _get(endpoint: str, params: dict) -> list:
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json() or []
    except Exception:
        return []


def _name(item: dict) -> str:
    names = item.get("name") or []
    return names[0].get("text", "") if names else ""


def _school_days(pais: str, year: int, region: str | None, subdiv_map: dict) -> set[date]:
    params = {
        "countryIsoCode": pais,
        "languageIsoCode": pais,
        "validFrom": f"{year}-01-01",
        "validTo": f"{year}-12-31",
    }
    subdiv = subdiv_map.get(region or "")
    if subdiv:
        params["subdivisionCode"] = subdiv
    days: set[date] = set()
    for item in _get("SchoolHolidays", params):
        try:
            d = date.fromisoformat(item["startDate"])
            end = date.fromisoformat(item["endDate"])
            while d <= end:
                days.add(d)
                d += timedelta(days=1)
        except Exception:
            continue
    return days


def _public_holidays(pais: str, year: int, region: str | None, subdiv_map: dict) -> list[dict]:
    params = {
        "countryIsoCode": pais,
        "languageIsoCode": pais,
        "validFrom": f"{year}-01-01",
        "validTo": f"{year}-12-31",
    }
    subdiv = subdiv_map.get(region or "")
    if subdiv:
        params["subdivisionCode"] = subdiv
    result = []
    for item in _get("PublicHolidays", params):
        try:
            result.append(
                {
                    "fecha": date.fromisoformat(item["startDate"]),
                    "name": _name(item),
                    "nationwide": item.get("nationwide", True),
                }
            )
        except Exception:
            continue
    return result


def _collect(
    ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date
) -> tuple[list[dict], list[dict]]:
    subdiv_es = cfg.get("subdivisiones_es", _SUBDIV_ES_DEFAULT)
    subdiv_mx = cfg.get("subdivisiones_mx", _SUBDIV_MX_DEFAULT)
    years = list(range(date_from.year, date_to.year + 1))

    señales: list[dict] = []
    eventos: list[dict] = []

    for ubi in ubicaciones:
        ubi_id = ubi["ubicacion_id"]
        pais = ubi.get("pais_codigo", "ES")
        region = ubi.get("region_code")
        subdiv_map = subdiv_es if pais == "ES" else subdiv_mx

        for year in years:
            for d in _school_days(pais, year, region, subdiv_map):
                if date_from <= d <= date_to:
                    señales.append(
                        {
                            "fecha": d.isoformat(),
                            "ubicacion_id": ubi_id,
                            "señal_id": "ev_vacaciones_escolares",
                            "valor": 1.0,
                        }
                    )
                    eventos.append(
                        {
                            "ubicacion_id": ubi_id,
                            "pais_codigo": pais,
                            "evento_key": "vacaciones_escolares",
                            "fecha_inicio": d.isoformat(),
                            "fecha_fin": d.isoformat(),
                            "fuente": "open_holidays",
                            "source_key": f"oh_school:{pais}:{region or ''}:{d}",
                            "metadata": {"pais": pais, "region": region},
                        }
                    )

            for fh in _public_holidays(pais, year, region, subdiv_map):
                if not fh["nationwide"] and date_from <= fh["fecha"] <= date_to:
                    señales.append(
                        {
                            "fecha": fh["fecha"].isoformat(),
                            "ubicacion_id": ubi_id,
                            "señal_id": "ev_festivo_regional",
                            "valor": 1.0,
                        }
                    )
                    eventos.append(
                        {
                            "ubicacion_id": ubi_id,
                            "pais_codigo": pais,
                            "evento_key": "festivo_regional",
                            "fecha_inicio": fh["fecha"].isoformat(),
                            "fecha_fin": fh["fecha"].isoformat(),
                            "fuente": "open_holidays",
                            "source_key": (
                                f"oh_ph:{pais}:{region or ''}:{fh['fecha']}:{fh['name']}"
                            ),
                            "metadata": {"nombre": fh["name"]},
                        }
                    )

    return señales, eventos


@dlt.source
def source(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    señales, eventos = _collect(ubicaciones, cfg, date_from, date_to)

    @dlt.resource(
        name="señal", write_disposition="merge", primary_key=["fecha", "ubicacion_id", "señal_id"]
    )
    def señal_res():
        yield from señales

    @dlt.resource(name="evento", write_disposition="merge", primary_key=["source_key"])
    def evento_res():
        yield from eventos

    yield señal_res()
    yield evento_res()
