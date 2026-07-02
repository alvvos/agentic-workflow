"""
Cliente GeoEnrichment Esri — obtiene variables demográficas y de gasto por radio.

fetch_geoenrich(ubicacion_id, lat, lon) → dict[str, float | None]
  Hace 2 llamadas al API de GeoEnrichment:
    1. Ring buffer [400, 800, 1200]m → población acumulada por isócrona peatonal.
    2. Círculo 800m → demografía, renta, gasto, empleo, compras online, inmobiliario.
  Devuelve {señal_id: valor} listo para ingestar en snapshots_geo.

Requiere ESRI_KEY en el entorno (.env o variable de sistema).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("esri_client")

_GEO_ENRICH_URL = (
    "https://geoenrich.arcgis.com/arcgis/rest/services/"
    "World/geoenrichmentserver/GeoEnrichment/enrich"
)

# {esri_collection.variable → señal_id}  — usado en el círculo 800m
_CIRCLE_VAR_MAP: dict[str, str] = {
    # ── Edad 5 años (5YearIncrementsAIS, 2023) ────────────────────────────────
    "5YearIncrementsAIS.POPAG00": "pob_0_4",
    "5YearIncrementsAIS.POPAG05": "pob_5_9",
    "5YearIncrementsAIS.POPAG10": "pob_10_14",
    "5YearIncrementsAIS.POPAG15": "pob_15_19",
    "5YearIncrementsAIS.POPAG20": "pob_20_24",
    "5YearIncrementsAIS.POPAG25": "pob_25_29",
    "5YearIncrementsAIS.POPAG30": "pob_30_34",
    "5YearIncrementsAIS.POPAG35": "pob_35_39",
    "5YearIncrementsAIS.POPAG40": "pob_40_44",
    "5YearIncrementsAIS.POPAG45": "pob_45_49",
    "5YearIncrementsAIS.POPAG50": "pob_50_54",
    "5YearIncrementsAIS.POPAG55": "pob_55_59",
    "5YearIncrementsAIS.POPAG60": "pob_60_64",
    "5YearIncrementsAIS.POPAG65": "pob_65_69",
    "5YearIncrementsAIS.POPAG70": "pob_70_74",
    "5YearIncrementsAIS.POPAG75": "pob_75_79",
    "5YearIncrementsAIS.POPAG80": "pob_80_84",
    "5YearIncrementsAIS.POPAG85": "pob_85_plus",
    # ── Renta (IncomeTotalsAIS, 2023) ─────────────────────────────────────────
    "IncomeTotalsAIS.NINCHA": "renta_hogar_anual",
    "IncomeTotalsAIS.NINCHM": "renta_hogar_mensual",
    "IncomeTotalsAIS.NINCCA": "renta_per_capita",
    # ── Composición de hogar (IncomeTotalsAIS, 2023) ──────────────────────────
    "IncomeTotalsAIS.TOTYOSI": "hogares_jovenes_solos",
    "IncomeTotalsAIS.TOTYOCO": "hogares_parejas_jovenes",
    "IncomeTotalsAIS.TOTADCO": "hogares_parejas_adultas",
    "IncomeTotalsAIS.TOTFUSMA": "hogares_familias_hijos",
    "IncomeTotalsAIS.TOTSIFA": "hogares_monoparentales",
    # ── Totales de hogar (HouseholdTotalsAIS, 2023) ───────────────────────────
    "HouseholdTotalsAIS.HHOLDS": "n_hogares_total",
    "HouseholdTotalsAIS.PEOFAM": "tamanio_medio_hogar",
    # ── Ingresos por quintil (HouseholdsByIncomeAIS, 2023) ────────────────────
    "HouseholdsByIncomeAIS.THINC5M": "hogares_renta_alta",
    "HouseholdsByIncomeAIS.THINC4M": "hogares_renta_media_alta",
    # ── Salud financiera del hogar (HouseholdsByIncomeAIS, 2023) ─────────────
    "HouseholdsByIncomeAIS.DOCAYE": "puede_afrontar_imprevistos_pct",
    "HouseholdsByIncomeAIS.HOMAEASE": "llega_mes_con_facilidad_pct",
    "HouseholdsByIncomeAIS.HORIPOYE": "en_riesgo_pobreza_pct",
    # ── Gasto en ropa y calzado (ClothingAIS, 2023) ───────────────────────────
    "ClothingAIS.SPCLOFO": "gasto_ropa_calzado",
    "ClothingAIS.SPCLOTH": "gasto_ropa",
    "ClothingAIS.SPFOOTW": "gasto_calzado",
    # ── Cuidado personal (SpendingTotalsAIS, 2023) ────────────────────────────
    "SpendingTotalsAIS.SPPCARE": "gasto_cuidado_personal",
    # ── Ocio y cultura (EntertainmentAIS, 2023) ───────────────────────────────
    "EntertainmentAIS.SPLEISU": "gasto_ocio_cultura",
    "EntertainmentAIS.SPLHOLI": "gasto_vacaciones",
    # ── Restaurantes y comunicaciones (MiscellaneousAIS, 2023) ───────────────
    "MiscellaneousAIS.SPHOTRE": "gasto_restaurantes",
    "MiscellaneousAIS.SPCOMM": "gasto_comunicaciones",
    # ── Alimentación (FoodAndDrinksAIS, 2023) ─────────────────────────────────
    "FoodAndDrinksAIS.SPFOODR": "gasto_alimentacion",
    # ── Transporte (TransportationAIS, 2023) ──────────────────────────────────
    "TransportationAIS.SPTRANS": "gasto_transporte",
    # ── Empleo (EmploymentTotalsAIS, 2023) ────────────────────────────────────
    "EmploymentTotalsAIS.UNERATE": "tasa_desempleo",
    "EmploymentTotalsAIS.UNERATE24": "tasa_desempleo_jovenes",
    "EmploymentTotalsAIS.TOTOCCME": "empleados_por_hogar",
    # ── Compras online (OnlineShoppingAIS, 2023) ──────────────────────────────
    "OnlineShoppingAIS.PUTHINT": "pct_compras_online",
    "OnlineShoppingAIS.PROPURSPO": "online_ropa_deporte_pct",
    "OnlineShoppingAIS.WHELAIN": "online_ultimo_mes_pct",
    # ── Precio inmobiliario (PropertyValueAIS, 2023) ──────────────────────────
    "PropertyValueAIS.AVPRIRENP": "precio_piso_alquiler",
    # ── Poder de compra (KeyFacts, 2025) ──────────────────────────────────────
    "KeyFacts.PPIDX_CY": "indice_poder_compra",
    "KeyFacts.PPPC_CY": "poder_compra_pc",
}


def _geoenrich_call(
    lat: float,
    lon: float,
    buffer_radii: list[int],
    analysis_variables: list[str],
    token: str,
) -> list[dict]:
    """Llama al GeoEnrichment API y devuelve una lista de atributos (uno por anillo)."""
    study_areas = json.dumps(
        [
            {
                "geometry": {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}},
                "areaType": "RingBuffer",
                "bufferUnits": "esriMeters",
                "bufferRadii": buffer_radii,
            }
        ]
    )
    params = urllib.parse.urlencode(
        {
            "studyAreas": study_areas,
            "analysisVariables": ",".join(analysis_variables),
            "returnGeometry": "false",
            "f": "json",
            "token": token,
        }
    )
    req = urllib.request.Request(_GEO_ENRICH_URL, data=params.encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(f"GeoEnrichment error: {data['error']}")
    feature_sets = data.get("results", [{}])[0].get("value", {}).get("FeatureSet", [])
    if not feature_sets:
        return []
    return [f.get("attributes", {}) for f in feature_sets[0].get("features", [])]


def fetch_geoenrich(ubicacion_id: str, lat: float, lon: float) -> dict[str, float | None]:
    """
    Consulta Esri GeoEnrichment y devuelve {señal_id: valor} para insertar
    en snapshots_geo.

    Call 1 — Ring buffer [400, 800, 1200]m con KeyFacts.TOTPOP_CY:
      Devuelve población por anillo (bandas anulares). Se acumula para obtener
      la población dentro de cada isócrona peatonal.

    Call 2 — Círculo 800m con todas las variables AIS + KeyFacts:
      Demografía por edad, renta, composición de hogar, gasto retail,
      empleo, compras online, precios inmobiliarios y poder de compra.
    """
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        raise RuntimeError("ESRI_KEY no encontrado en el entorno")

    resultado: dict[str, float | None] = {}

    # ── Call 1: Isócronas peatonales ─────────────────────────────────────────
    try:
        rings = _geoenrich_call(
            lat,
            lon,
            buffer_radii=[400, 800, 1200],
            analysis_variables=["KeyFacts.TOTPOP_CY"],
            token=token,
        )
        if len(rings) >= 3:
            r0 = float(rings[0].get("TOTPOP_CY") or 0)
            r1 = float(rings[1].get("TOTPOP_CY") or 0)
            r2 = float(rings[2].get("TOTPOP_CY") or 0)
            resultado["poblacion_5min"] = r0
            resultado["poblacion_10min"] = r0 + r1
            resultado["poblacion_15min"] = r0 + r1 + r2
        else:
            log.warning(
                "[%s] ring call devolvió %d features (esperadas 3)",
                ubicacion_id,
                len(rings),
            )
    except Exception as exc:
        log.error("[%s] ring call FAILED — %s", ubicacion_id, exc)

    # ── Call 2: Variables AIS + KeyFacts en círculo 800m ─────────────────────
    try:
        circle = _geoenrich_call(
            lat,
            lon,
            buffer_radii=[800],
            analysis_variables=list(_CIRCLE_VAR_MAP.keys()),
            token=token,
        )
        if circle:
            attrs = circle[0]
            for esri_spec, señal_id in _CIRCLE_VAR_MAP.items():
                var_name = esri_spec.split(".")[-1]
                val = attrs.get(var_name)
                resultado[señal_id] = float(val) if val is not None else None
        else:
            log.warning("[%s] circle call devolvió 0 features", ubicacion_id)
    except Exception as exc:
        log.error("[%s] circle call FAILED — %s", ubicacion_id, exc)

    return resultado
