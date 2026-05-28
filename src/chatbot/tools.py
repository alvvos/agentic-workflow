"""
Funciones de acceso a datos locales expuestas como herramientas MCP.
Cada función es pura Python — pueden llamarse directamente desde el cliente
o envolverse en un servidor FastMCP para transporte stdio/HTTP.
"""
import json
import requests
from glob import glob
from pathlib import Path

import holidays as _holidays_lib
import pandas as pd

_DATA_DIR   = Path(__file__).parent.parent / "data"
_GEO_PATH   = _DATA_DIR / "geo_features.json"
_UBIC_PATH  = _DATA_DIR / "todas_las_ubicaciones.json"
_RAW_GLOB   = str(_DATA_DIR / "dataset_*.csv")
MAX_DAYS    = 90


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_ubicaciones() -> list:
    with open(_UBIC_PATH, encoding="utf-8") as f:
        return json.load(f)


def _find_location(location_uuid: str) -> dict | None:
    for org in _load_ubicaciones():
        for loc in org.get("locations", []):
            if loc["uuid"] == location_uuid:
                return {"org": org.get("name"), **loc}
    return None


def _load_dataset(session_id: str = "local_dev") -> pd.DataFrame:
    path = _DATA_DIR / f"dataset_{session_id}.csv"
    if not path.exists():
        # fallback: cualquier CSV disponible
        files = sorted(glob(_RAW_GLOB))
        if not files:
            return pd.DataFrame()
        path = files[-1]
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


# ── Herramienta 1: get_pm_data ────────────────────────────────────────────────

def get_pm_data(
    location_id: str,
    fecha_inicio: str,
    fecha_fin: str,
    zone_uuid: str | None = None,
    session_id: str = "local_dev",
) -> dict:
    """
    Devuelve métricas de tráfico y comportamiento de visitantes para una
    ubicación en un rango de fechas. Opcionalmente filtra por zona.

    Retorna resumen con: total visitas, media diaria, pico horario,
    tiempo de permanencia, comparativa WoW y perfil de visitantes.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}
    if t1 < t0:
        return {"error": "La fecha de inicio debe ser anterior a la fecha de fin."}
    delta_days = (t1 - t0).days
    if delta_days > MAX_DAYS:
        return {
            "error": (
                f"El rango solicitado abarca {delta_days} días. "
                f"El máximo permitido es {MAX_DAYS} días por consulta. "
                "Divide el periodo en intervalos más cortos."
            )
        }

    df = _load_dataset(session_id)
    if df.empty:
        return {"error": "No hay datos disponibles en este momento."}

    mask = (
        (df["location_id"] == location_id) &
        (df["fecha"] >= t0) &
        (df["fecha"] <= t1)
    )
    if zone_uuid:
        mask &= df["zone_uuid"] == zone_uuid

    sub = df[mask].copy()
    if sub.empty:
        return {"error": f"Sin datos para location_id={location_id} en el rango {fecha_inicio}→{fecha_fin}."}

    # Métricas base
    total_dias  = delta_days + 1
    total_vis   = int(sub["total_visits"].sum())
    media_dia   = round(total_vis / max(len(sub), 1), 0)
    dwell_med   = round(sub["dwell_time"].mean(), 0)
    uv_total    = int(sub["unique_visitors"].sum())
    new_vis     = int(sub["new_visitors"].dropna().sum())

    # Hora pico (parsear hourly_visits JSON)
    hora_pico = None
    try:
        hourly_all = [0] * 24
        for row in sub["hourly_visits"].dropna():
            arr = json.loads(row) if isinstance(row, str) else row
            for h, v in enumerate(arr):
                hourly_all[h] += v
        hora_pico = int(hourly_all.index(max(hourly_all)))
    except Exception:
        pass

    # Comparativa WoW: última semana vs semana anterior
    wow_pct = None
    try:
        t1 = pd.Timestamp(fecha_fin)
        t0 = t1 - pd.Timedelta(days=6)
        t_prev_1 = t0 - pd.Timedelta(days=1)
        t_prev_0 = t_prev_1 - pd.Timedelta(days=6)
        v_now  = df[(df["location_id"] == location_id) & df["fecha"].between(t0, t1)]["total_visits"].sum()
        v_prev = df[(df["location_id"] == location_id) & df["fecha"].between(t_prev_0, t_prev_1)]["total_visits"].sum()
        if v_prev:
            wow_pct = round((v_now - v_prev) / v_prev * 100, 1)
    except Exception:
        pass

    # Info de la ubicación
    loc_info = _find_location(location_id)
    nombre   = loc_info.get("name", location_id) if loc_info else location_id
    org      = loc_info.get("org", "") if loc_info else ""

    return {
        "ubicacion": nombre,
        "organizacion": org,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin, "dias": total_dias},
        "visitas_totales": total_vis,
        "visitas_media_diaria": int(media_dia),
        "visitantes_unicos": uv_total,
        "visitantes_nuevos": new_vis,
        "pct_nuevos": round(new_vis / uv_total * 100, 1) if uv_total else None,
        "dwell_time_seg": int(dwell_med),
        "hora_pico": hora_pico,
        "wow_pct": wow_pct,
        "filas_analizadas": len(sub),
    }


# ── Herramienta 2: get_gis_data ───────────────────────────────────────────────

def get_gis_data(location_uuid: str, fecha: str | None = None) -> dict:
    """
    Devuelve los datos geoespaciales almacenados localmente para una ubicación.
    Si fecha es None devuelve el snapshot activo; si se proporciona fecha,
    devuelve el snapshot válido en ese momento (para análisis histórico).

    Incluye: población accesible, renta, gasto en ropa, presión online,
    salud financiera del área y entorno competitivo (si disponible).
    """
    try:
        from src.data_processing.geo_enrichment import get_geo_vals
        vals = get_geo_vals(location_uuid, fecha)
    except Exception as e:
        return {"error": f"No se pudo cargar geo_features.json: {e}"}

    activos = {k: v for k, v in vals.items() if v is not None}
    if not activos:
        return {"sin_datos": True, "location_uuid": location_uuid}

    loc_info = _find_location(location_uuid)
    nombre   = loc_info.get("name", location_uuid) if loc_info else location_uuid

    result = {"ubicacion": nombre, "location_uuid": location_uuid}

    # Alcance peatonal
    if activos.get("poblacion_5min"):
        result["alcance_peatonal"] = {
            "5min_hab":  activos.get("poblacion_5min"),
            "10min_hab": activos.get("poblacion_10min"),
            "15min_hab": activos.get("poblacion_15min"),
        }

    # Perfil económico
    if activos.get("renta_hogar_anual"):
        result["perfil_economico"] = {
            "renta_hogar_anual_eur":    activos.get("renta_hogar_anual"),
            "renta_hogar_mensual_eur":  activos.get("renta_hogar_mensual"),
            "n_hogares_800m":           activos.get("n_hogares_total"),
            "pct_hogares_renta_alta":   (
                round((activos.get("hogares_renta_alta", 0) or 0) /
                      activos["n_hogares_total"] * 100, 1)
                if activos.get("n_hogares_total") else None
            ),
        }

    # Gasto retail
    if activos.get("gasto_ropa_calzado"):
        result["gasto_retail"] = {
            "ropa_calzado_eur_hogar_año": activos.get("gasto_ropa_calzado"),
            "cuidado_personal_eur":       activos.get("gasto_cuidado_personal"),
            "ocio_cultura_eur":           activos.get("gasto_ocio_cultura"),
        }

    # Presión online
    if activos.get("pct_compras_online") and activos.get("n_hogares_total"):
        nhog = activos["n_hogares_total"]
        result["canal_online"] = {
            "pct_compra_online":         round(activos["pct_compras_online"] / nhog * 100, 1),
            "pct_compra_ropa_online":    round((activos.get("online_ropa_deporte_pct") or 0) / nhog * 100, 1),
        }

    # Salud financiera
    if activos.get("puede_afrontar_imprevistos_pct") and activos.get("n_hogares_total"):
        nhog = activos["n_hogares_total"]
        result["salud_financiera"] = {
            "pct_puede_afrontar_imprevistos": round(activos["puede_afrontar_imprevistos_pct"] / nhog * 100, 1),
            "pct_riesgo_pobreza":             round((activos.get("en_riesgo_pobreza_pct") or 0) / nhog * 100, 1),
        }

    # Entorno competitivo (Phase 2, si disponible)
    if activos.get("n_competidores_500m") is not None:
        result["entorno_competitivo"] = {
            "competidores_500m":         activos.get("n_competidores_500m"),
            "dist_competidor_cercano_m": activos.get("dist_competidor_cercano_m"),
            "dist_transporte_m":         activos.get("dist_transporte_min_m"),
        }

    return result


# ── Herramienta 3: get_weather_holidays ───────────────────────────────────────

def get_weather_holidays(
    location_id: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> dict:
    """
    Devuelve datos meteorológicos (temp. máx/mín, precipitación) y festivos
    regionales para una ubicación y rango de fechas.
    Fuente clima: Open-Meteo archive API (gratuita).
    Fuente festivos: librería `holidays` (festivos nacionales + autonómicos).
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}

    if t1 < t0:
        return {"error": "La fecha de inicio debe ser anterior a la fecha de fin."}
    delta_days = (t1 - t0).days
    if delta_days > MAX_DAYS:
        return {
            "error": (
                f"El rango solicitado abarca {delta_days} días. "
                f"El máximo permitido es {MAX_DAYS} días por consulta."
            )
        }

    loc = _find_location(location_id)
    if not loc:
        return {"error": f"Ubicación {location_id} no encontrada."}

    lat          = loc.get("lat") or 40.4168
    lon          = loc.get("lon") or -3.7038
    region_code  = loc.get("region_code", "MD")

    # ── Festivos ─────────────────────────────────────────────────────────────
    years = list({t0.year, t1.year})
    try:
        cal = _holidays_lib.Spain(subdiv=region_code, years=years)
    except Exception:
        cal = _holidays_lib.Spain(years=years)

    dates = pd.date_range(fecha_inicio, fecha_fin, freq="D")
    festivos = [
        {"fecha": d.strftime("%Y-%m-%d"), "nombre": cal[d.date()]}
        for d in dates if d.date() in cal
    ]

    # ── Clima (Open-Meteo archive) ────────────────────────────────────────────
    weather_daily: dict = {}
    try:
        url = (
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={fecha_inicio}&end_date={fecha_fin}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone=Europe%2FMadrid"
        )
        resp = requests.get(url, timeout=10).json()
        for i, fstr in enumerate(resp["daily"]["time"]):
            weather_daily[fstr] = {
                "tmax":             resp["daily"]["temperature_2m_max"][i],
                "tmin":             resp["daily"]["temperature_2m_min"][i],
                "precipitacion_mm": resp["daily"]["precipitation_sum"][i],
            }
    except Exception:
        pass

    # ── Resumen por día ───────────────────────────────────────────────────────
    por_dia = []
    for d in dates:
        fstr   = d.strftime("%Y-%m-%d")
        entry  = {"fecha": fstr, "dia_semana": d.strftime("%A")}
        festivo = cal.get(d.date())
        if festivo:
            entry["festivo"] = festivo
        w = weather_daily.get(fstr)
        if w:
            entry["tmax"]             = w["tmax"]
            entry["tmin"]             = w["tmin"]
            entry["precipitacion_mm"] = w["precipitacion_mm"]
            entry["lluvia"]           = (w["precipitacion_mm"] or 0) > 1.0
        por_dia.append(entry)

    return {
        "ubicacion":        loc.get("name", location_id),
        "region":           region_code,
        "periodo":          {"inicio": fecha_inicio, "fin": fecha_fin, "dias": delta_days + 1},
        "festivos":         festivos,
        "n_festivos":       len(festivos),
        "clima_disponible": bool(weather_daily),
        "por_dia":          por_dia,
    }
