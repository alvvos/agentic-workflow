"""
Funciones de acceso a datos locales expuestas como herramientas MCP.
Cada función es pura Python — pueden llamarse directamente desde el cliente
o envolverse en un servidor FastMCP para transporte stdio/HTTP.
"""

import json
from glob import glob
from pathlib import Path

import holidays as _holidays_lib
import pandas as pd
import requests

_DATA_DIR = Path(__file__).parent.parent / "data"
_RAW_GLOB = str(_DATA_DIR / "dataset_*.csv")
MAX_DAYS = 90
MAX_DAYS_EXT = 760  # external features allow longer windows


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_location(location_uuid: str) -> dict | None:
    try:
        from src.db.queries import get_location_by_uuid, get_zones_for_loc

        loc = get_location_by_uuid(location_uuid)
        if loc is None:
            return None
        loc["zones"] = [
            {
                "uuid": z["zona_id"],
                "zoneName": z["nombre"],
                "oculta": z["oculta"],
                "zoneType": z["tipo_zona"],
            }
            for z in get_zones_for_loc(location_uuid)
        ]
        return loc
    except Exception:
        return None


def _load_dataset(session_id: str = "local_dev") -> pd.DataFrame:
    try:
        from src.db.store import get_conn

        df = (
            get_conn()
            .execute(
                """
            SELECT fecha, ubicacion_id AS location_id, zona_id,
                   total_visitas AS total_visits, visitantes_unicos AS unique_visitors,
                   visitantes_nuevos AS new_visitors,
                   tiempo_estancia_min AS dwell_time, visitas_horarias AS hourly_visits
            FROM visitas ORDER BY fecha
        """
            )
            .df()
        )
        if not df.empty:
            df["fecha"] = pd.to_datetime(df["fecha"])
            return df
    except Exception:
        pass
    # Fallback: CSV (entorno sin DB o tests con datos sintéticos)
    path = _DATA_DIR / f"dataset_{session_id}.csv"
    if not path.exists():
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

    mask = (df["location_id"] == location_id) & (df["fecha"] >= t0) & (df["fecha"] <= t1)
    if zone_uuid:
        mask &= df["zona_id"] == zone_uuid

    sub = df[mask].copy()
    if sub.empty:
        return {
            "error": f"Sin datos para location_id={location_id} en el rango {fecha_inicio}→{fecha_fin}."
        }

    # Métricas base
    total_dias = delta_days + 1
    total_vis = int(sub["total_visits"].sum())
    media_dia = round(total_vis / max(sub["fecha"].nunique(), 1), 0)
    dwell_med = round(sub["dwell_time"].mean(), 0)
    uv_total = int(sub["unique_visitors"].sum())
    new_vis = int(sub["new_visitors"].dropna().sum())

    # Hora pico (parsear hourly_visits JSON — lista de 24 valores o dict {hour: count})
    hora_pico = None
    try:
        hourly_all = [0] * 24
        for row in sub["hourly_visits"].dropna():
            arr = json.loads(row) if isinstance(row, str) else row
            if isinstance(arr, dict):
                for h, v in arr.items():
                    hourly_all[int(h)] += float(v or 0)
            elif isinstance(arr, list):
                for h, v in enumerate(arr):
                    hourly_all[h] += float(v or 0)
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
        v_now = df[(df["location_id"] == location_id) & df["fecha"].between(t0, t1)][
            "total_visits"
        ].sum()
        v_prev = df[(df["location_id"] == location_id) & df["fecha"].between(t_prev_0, t_prev_1)][
            "total_visits"
        ].sum()
        if v_prev:
            wow_pct = round((v_now - v_prev) / v_prev * 100, 1)
    except Exception:
        pass

    # Info de la ubicación
    loc_info = _find_location(location_id)
    nombre = loc_info.get("name", location_id) if loc_info else location_id
    org = loc_info.get("org", "") if loc_info else ""

    return {
        "ubicacion": nombre,
        "organizacion": org,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin, "dias": total_dias},
        "visitas_totales": total_vis,
        "visitas_media_diaria": int(media_dia),
        "visitantes_unicos": uv_total,
        "visitantes_nuevos": new_vis,
        "pct_nuevos": round(new_vis / uv_total * 100, 1) if uv_total else None,
        "dwell_time_min": int(dwell_med),
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
        return {"error": f"No se pudieron cargar los datos geoespaciales: {e}"}

    activos = {k: v for k, v in vals.items() if v is not None}
    if not activos:
        return {"sin_datos": True, "location_uuid": location_uuid}

    loc_info = _find_location(location_uuid)
    nombre = loc_info.get("name", location_uuid) if loc_info else location_uuid

    result = {"ubicacion": nombre, "location_uuid": location_uuid}

    # Alcance peatonal
    if activos.get("poblacion_5min"):
        result["alcance_peatonal"] = {
            "5min_hab": activos.get("poblacion_5min"),
            "10min_hab": activos.get("poblacion_10min"),
            "15min_hab": activos.get("poblacion_15min"),
        }

    # Perfil económico
    if activos.get("renta_hogar_anual"):
        result["perfil_economico"] = {
            "renta_hogar_anual_eur": activos.get("renta_hogar_anual"),
            "renta_hogar_mensual_eur": activos.get("renta_hogar_mensual"),
            "n_hogares_800m": activos.get("n_hogares_total"),
            "pct_hogares_renta_alta": (
                round(
                    (activos.get("hogares_renta_alta", 0) or 0) / activos["n_hogares_total"] * 100,
                    1,
                )
                if activos.get("n_hogares_total")
                else None
            ),
        }

    # Gasto retail
    if activos.get("gasto_ropa_calzado"):
        result["gasto_retail"] = {
            "ropa_calzado_eur_hogar_año": activos.get("gasto_ropa_calzado"),
            "cuidado_personal_eur": activos.get("gasto_cuidado_personal"),
            "ocio_cultura_eur": activos.get("gasto_ocio_cultura"),
        }

    # Presión online
    if activos.get("pct_compras_online") and activos.get("n_hogares_total"):
        nhog = activos["n_hogares_total"]
        result["canal_online"] = {
            "pct_compra_online": round(activos["pct_compras_online"] / nhog * 100, 1),
            "pct_compra_ropa_online": round(
                (activos.get("online_ropa_deporte_pct") or 0) / nhog * 100, 1
            ),
        }

    # Salud financiera
    if activos.get("puede_afrontar_imprevistos_pct") and activos.get("n_hogares_total"):
        nhog = activos["n_hogares_total"]
        result["salud_financiera"] = {
            "pct_puede_afrontar_imprevistos": round(
                activos["puede_afrontar_imprevistos_pct"] / nhog * 100, 1
            ),
            "pct_riesgo_pobreza": round(
                (activos.get("en_riesgo_pobreza_pct") or 0) / nhog * 100, 1
            ),
        }

    # Entorno competitivo (Phase 2, si disponible)
    if activos.get("n_competidores_500m") is not None:
        result["entorno_competitivo"] = {
            "competidores_500m": activos.get("n_competidores_500m"),
            "dist_competidor_cercano_m": activos.get("dist_competidor_cercano_m"),
            "dist_transporte_m": activos.get("dist_transporte_min_m"),
        }

    return result


# ── Herramienta 4: get_forecast ──────────────────────────────────────────────


def get_forecast(
    location_uuid: str,
    zone_uuid: str,
    n_dias: int = 14,
    session_id: str = "local_dev",
) -> dict:
    """
    Ejecuta el modelo predictivo XGBoost y devuelve las predicciones de visitas
    para los próximos N días. Incluye métricas de precisión si hay datos reales
    con los que comparar (accuracy, MAE, WMAPE).
    """
    if not 1 <= n_dias <= 90:
        return {"error": "n_dias debe estar entre 1 y 90."}

    from datetime import date

    from src.db.queries import get_df_enriquecido
    from src.services.ml_predictivo import ejecutar_auditoria_predictiva

    df = get_df_enriquecido(location_uuid, session_id)

    if df is None or df.empty:
        return {"error": f"Sin datos para la ubicación {location_uuid}."}

    falso_hoy = date.today().isoformat()
    result = ejecutar_auditoria_predictiva(df, location_uuid, zone_uuid, falso_hoy, n_dias)
    if "error" in result:
        return result

    grafica = result.get("grafica", {})
    fechas = grafica.get("fechas", [])
    predichos = grafica.get("predichos", [])
    reales = grafica.get("reales", [])

    predicciones = []
    for f, p, r in zip(fechas, predichos, reales):
        entry = {"fecha": f, "prediccion": int(round(float(p))) if p is not None else None}
        if r is not None:
            entry["real"] = int(round(float(r)))
        predicciones.append(entry)

    loc_info = _find_location(location_uuid)
    nombre = loc_info.get("name", location_uuid) if loc_info else location_uuid

    return {
        "ubicacion": nombre,
        "horizonte_dias": n_dias,
        "metricas": result.get("metricas", {}),
        "desde_cache": result.get("cache_hit", False),
        "predicciones": predicciones,
    }


# ── Herramienta 5: get_anomalies ──────────────────────────────────────────────


def get_anomalies(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
    zone_uuid: str | None = None,
    session_id: str = "local_dev",
) -> dict:
    """
    Detecta días anómalos (z-score > 2.0) en el tráfico de visitantes.
    Devuelve la lista de anomalías ordenada por magnitud, con contexto de
    media del periodo y tipo (pico o caída).
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}

    df = _load_dataset(session_id)
    if df.empty:
        return {"error": "No hay datos disponibles."}

    mask = (df["location_id"] == location_uuid) & (df["fecha"] >= t0) & (df["fecha"] <= t1)
    if zone_uuid:
        mask &= df["zona_id"] == zone_uuid
    sub = df[mask].copy()
    if sub.empty:
        return {"error": f"Sin datos para el rango {fecha_inicio}→{fecha_fin}."}

    agg = sub.groupby(["fecha", "zona_id"])["total_visits"].sum().reset_index()

    loc_info = _find_location(location_uuid)
    nombre = loc_info.get("name", location_uuid) if loc_info else location_uuid
    zone_map = {z["uuid"]: z["zoneName"] for z in (loc_info or {}).get("zones", [])}

    anomalias = []
    for zona, grp in agg.groupby("zona_id"):
        grp = grp.sort_values("fecha")
        valores = grp["total_visits"].values
        if len(valores) < 7:
            continue
        media, std = float(valores.mean()), float(valores.std())
        if std == 0:
            continue
        for _, row in grp.iterrows():
            z = (row["total_visits"] - media) / std
            if abs(z) > 2.0:
                anomalias.append(
                    {
                        "fecha": row["fecha"].strftime("%Y-%m-%d"),
                        "zona": zone_map.get(zona, zona),
                        "visitas": int(row["total_visits"]),
                        "media_periodo": round(media, 1),
                        "z_score": round(float(z), 2),
                        "tipo": "pico" if z > 0 else "caída",
                    }
                )

    anomalias.sort(key=lambda x: abs(x["z_score"]), reverse=True)

    return {
        "ubicacion": nombre,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "total_anomalias": len(anomalias),
        "anomalias": anomalias,
    }


# ── Herramienta 6: get_hourly_breakdown ──────────────────────────────────────


def get_hourly_breakdown(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
    zone_uuid: str | None = None,
    session_id: str = "local_dev",
) -> dict:
    """
    Devuelve el desglose horario de visitas: hora pico global, media de visitas
    por franja horaria, y perfil por día de la semana.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}

    df = _load_dataset(session_id)
    if df.empty:
        return {"error": "No hay datos disponibles."}

    mask = (df["location_id"] == location_uuid) & (df["fecha"] >= t0) & (df["fecha"] <= t1)
    if zone_uuid:
        mask &= df["zona_id"] == zone_uuid
    sub = df[mask].dropna(subset=["hourly_visits"]).copy()
    if sub.empty:
        return {"error": "Sin datos de desglose horario en el periodo indicado."}

    _DIAS = {
        0: "Lunes",
        1: "Martes",
        2: "Miércoles",
        3: "Jueves",
        4: "Viernes",
        5: "Sábado",
        6: "Domingo",
    }

    rows = []
    for _, row in sub.iterrows():
        try:
            arr = (
                json.loads(row["hourly_visits"])
                if isinstance(row["hourly_visits"], str)
                else row["hourly_visits"]
            )
            if isinstance(arr, dict):
                # Normalize dict {hour_str: count} → list of 24 values
                arr = [float(arr.get(str(h), arr.get(h, 0)) or 0) for h in range(24)]
            if not isinstance(arr, list) or len(arr) != 24:
                continue
        except Exception:
            continue
        dia = _DIAS.get(row["fecha"].dayofweek, "")
        for h, v in enumerate(arr):
            rows.append({"dia_semana": dia, "hora": h, "visitas": float(v)})

    if not rows:
        return {"error": "No se pudieron parsear los datos horarios."}

    df_h = pd.DataFrame(rows)
    global_hora = df_h.groupby("hora")["visitas"].mean()
    hora_pico_global = int(global_hora.idxmax())

    por_dia = {}
    for dia_idx, dia_nombre in _DIAS.items():
        serie = df_h[df_h["dia_semana"] == dia_nombre].groupby("hora")["visitas"].mean()
        if serie.empty:
            continue
        hora_pico = int(serie.idxmax())
        por_dia[dia_nombre] = {
            "hora_pico": hora_pico,
            "visitas_hora_pico": round(float(serie.max()), 1),
            "total_medio_dia": round(float(serie.sum()), 1),
        }

    loc_info = _find_location(location_uuid)
    nombre = loc_info.get("name", location_uuid) if loc_info else location_uuid

    return {
        "ubicacion": nombre,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "hora_pico_global": hora_pico_global,
        "hora_pico_global_label": f"{hora_pico_global:02d}:00",
        "por_dia_semana": por_dia,
    }


# ── Herramienta 7: compare_locations ─────────────────────────────────────────

_METRICAS_VALIDAS = ["total_visits", "unique_visitors", "new_visitors", "dwell_time"]


def compare_locations(
    location_uuids: list,
    fecha_inicio: str,
    fecha_fin: str,
    metrica: str = "unique_visitors",
    session_id: str = "local_dev",
) -> dict:
    """
    Compara métricas de tráfico entre varias ubicaciones en el mismo periodo.
    Devuelve totales, medias diarias y ranking por la métrica seleccionada.
    """
    if metrica not in _METRICAS_VALIDAS:
        return {"error": f"Métrica no válida. Opciones: {', '.join(_METRICAS_VALIDAS)}"}
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}
    if t1 < t0:
        return {"error": "La fecha de inicio debe ser anterior a la fecha de fin."}

    df = _load_dataset(session_id)
    if df.empty:
        return {"error": "No hay datos disponibles."}

    resultados = []
    for uuid in location_uuids:
        sub = df[(df["location_id"] == uuid) & (df["fecha"] >= t0) & (df["fecha"] <= t1)].copy()
        loc_info = _find_location(uuid)
        nombre = loc_info.get("name", uuid) if loc_info else uuid
        if sub.empty:
            resultados.append({"nombre": nombre, "uuid": uuid, "sin_datos": True})
            continue
        if metrica == "dwell_time":
            total = None
            media_diaria = round(float(sub[metrica].mean()), 1)
        else:
            por_dia = sub.groupby("fecha")[metrica].sum()
            total = int(por_dia.sum())
            media_diaria = round(float(por_dia.mean()), 1)
        resultados.append(
            {
                "nombre": nombre,
                "uuid": uuid,
                "total": total,
                "media_diaria": media_diaria,
                "dias_con_datos": int(sub["fecha"].nunique()),
            }
        )

    ranking = sorted(
        [r for r in resultados if not r.get("sin_datos")],
        key=lambda x: x.get("media_diaria", 0),
        reverse=True,
    )

    return {
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "metrica": metrica,
        "n_ubicaciones": len(location_uuids),
        "ubicaciones": resultados,
        "ranking": [r["nombre"] for r in ranking],
    }


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

    lat = loc.get("lat") or 40.4168
    lon = loc.get("lon") or -3.7038
    region_code = loc.get("codigo_region")
    pais_codigo = loc.get("pais_codigo", "ES")

    # ── Festivos ─────────────────────────────────────────────────────────────
    years = list({t0.year, t1.year})
    try:
        country_cls = _holidays_lib.country_holidays(pais_codigo, subdiv=region_code, years=years)
        cal = country_cls
    except Exception:
        try:
            cal = _holidays_lib.country_holidays(pais_codigo, years=years)
        except Exception:
            cal = {}

    dates = pd.date_range(fecha_inicio, fecha_fin, freq="D")
    festivos = [
        {"fecha": d.strftime("%Y-%m-%d"), "nombre": cal[d.date()]} for d in dates if d.date() in cal
    ]

    # ── Clima (Open-Meteo archive) ────────────────────────────────────────────
    weather_daily: dict = {}
    try:
        tz = loc.get("timezone") or (
            "America/Mexico_City" if pais_codigo == "MX" else "Europe/Madrid"
        )
        url = (
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={fecha_inicio}&end_date={fecha_fin}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone={requests.utils.quote(tz)}"
        )
        resp = requests.get(url, timeout=10).json()
        for i, fstr in enumerate(resp["daily"]["time"]):
            weather_daily[fstr] = {
                "tmax": resp["daily"]["temperature_2m_max"][i],
                "tmin": resp["daily"]["temperature_2m_min"][i],
                "precipitacion_mm": resp["daily"]["precipitation_sum"][i],
            }
    except Exception:
        pass

    # ── Resumen por día ───────────────────────────────────────────────────────
    por_dia = []
    for d in dates:
        fstr = d.strftime("%Y-%m-%d")
        entry = {"fecha": fstr, "dia_semana": d.strftime("%A")}
        festivo = cal.get(d.date())
        if festivo:
            entry["festivo"] = festivo
        w = weather_daily.get(fstr)
        if w:
            entry["tmax"] = w["tmax"]
            entry["tmin"] = w["tmin"]
            entry["precipitacion_mm"] = w["precipitacion_mm"]
            entry["lluvia"] = (w["precipitacion_mm"] or 0) > 1.0
        por_dia.append(entry)

    return {
        "ubicacion": loc.get("name", location_id),
        "region": region_code,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin, "dias": delta_days + 1},
        "festivos": festivos,
        "n_festivos": len(festivos),
        "clima_disponible": bool(weather_daily),
        "por_dia": por_dia,
    }


# ── Herramienta 8: get_location_info ─────────────────────────────────────────


def get_location_info(location_uuid: str) -> dict:
    """
    Devuelve información completa de una ubicación: nombre, organización,
    dirección, coordenadas y lista de zonas con sus UUIDs.
    Útil para resolver preguntas sobre qué es una ubicación, dónde está,
    cuántas zonas tiene o cuáles son sus zonas.
    """
    try:
        from src.db.store import get_conn

        conn = get_conn()
        row = conn.execute(
            """SELECT u.ubicacion_id, u.nombre, u.ciudad, u.provincia,
                      u.direccion, u.lat, u.lon, u.codigo_postal,
                      o.nombre AS org_nombre, o.org_id
               FROM ubicaciones u
               JOIN organizaciones o ON o.org_id = u.org_id
               WHERE u.ubicacion_id = ?""",
            [location_uuid],
        ).fetchone()
    except Exception as e:
        return {"error": f"No se pudo consultar la ubicación: {e}"}

    if not row:
        return {"error": f"Ubicación {location_uuid} no encontrada."}

    uuid, nombre, ciudad, provincia, direccion, lat, lon, cp, org_nombre, org_uuid = row

    try:
        from src.db.store import get_conn

        conn = get_conn()
        zonas = conn.execute(
            """SELECT zona_id, nombre, tipo_zona, oculta
               FROM zonas WHERE ubicacion_id = ?
               ORDER BY nombre""",
            [location_uuid],
        ).fetchall()
    except Exception:
        zonas = []

    zonas_list = [
        {
            "uuid": z[0],
            "nombre": z[1],
            "tipo": z[2],
            "oculta": bool(z[3]),
        }
        for z in zonas
    ]

    return {
        "location_uuid": location_uuid,
        "nombre": nombre,
        "organizacion": org_nombre,
        "org_uuid": org_uuid,
        "ciudad": ciudad,
        "provincia": provincia,
        "direccion": direccion,
        "codigo_postal": cp,
        "coordenadas": {"lat": lat, "lon": lon},
        "n_zonas": len(zonas_list),
        "zonas": zonas_list,
    }


# ── Herramienta 9: get_active_features ───────────────────────────────────────


def get_active_features(location_uuid: str) -> dict:
    """
    Lista las features externas activas para una ubicación: tipo de dato
    (turistas, cruceros, metro, clima…), fuente, categoría, último valor
    registrado y fecha de última actualización.
    Útil para saber qué contexto externo tiene el modelo disponible.
    """
    try:
        from src.db.store import get_conn

        conn = get_conn()
        rows = conn.execute(
            """SELECT f.señal_id, r.fuente, r.categoria, r.notas,
                      f.evaluado_en
               FROM activacion_señales f
               LEFT JOIN señales r ON r.señal_id = f.señal_id
               WHERE f.ubicacion_id = ? AND f.status = 'active'
               ORDER BY r.categoria NULLS LAST, f.señal_id""",
            [location_uuid],
        ).fetchall()
    except Exception as e:
        return {"error": f"No se pudo consultar las features: {e}"}

    if not rows:
        loc = _find_location(location_uuid)
        nombre = loc.get("name", location_uuid) if loc else location_uuid
        return {
            "ubicacion": nombre,
            "n_features_activas": 0,
            "features": [],
            "nota": "No hay features externas activas para esta ubicación.",
        }

    feature_keys = [r[0] for r in rows]
    last_values: dict = {}
    try:
        from src.db.store import get_conn

        conn = get_conn()
        placeholders = ",".join(["?"] * len(feature_keys))
        lv_rows = conn.execute(
            f"""SELECT señal_id, valor, fecha::text
                FROM valores_señales
                WHERE ubicacion_id = ? AND señal_id IN ({placeholders})
                  AND valor IS NOT NULL
                ORDER BY fecha DESC""",
            [location_uuid] + feature_keys,
        ).fetchall()
        seen: set = set()
        for fk, val, fecha in lv_rows:
            if fk not in seen:
                last_values[fk] = {"value": val, "fecha": fecha}
                seen.add(fk)
    except Exception:
        pass

    features = []
    for fk, source, categoria, notas, evaluated_at in rows:
        entry: dict = {
            "feature_key": fk,
            "fuente": source,
            "categoria": categoria,
            "notas": notas,
        }
        if fk in last_values:
            entry["ultimo_valor"] = last_values[fk]["value"]
            entry["ultima_fecha"] = last_values[fk]["fecha"]
        features.append(entry)

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion": nombre,
        "n_features_activas": len(features),
        "features": features,
    }


# ── Herramienta 10: get_external_features ────────────────────────────────────


def get_external_features(
    location_uuid: str,
    feature_keys: list,
    fecha_inicio: str,
    fecha_fin: str,
    incluir_yoy: bool = False,
) -> dict:
    """
    Devuelve la serie temporal de features externas (turistas, pasajeros de
    crucero, viajeros de metro, temperatura, precipitación, etc.) para una
    ubicación y rango de fechas.
    Si incluir_yoy=True añade comparativa con el mismo periodo del año anterior.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}
    if t1 < t0:
        return {"error": "La fecha de inicio debe ser anterior a la fecha de fin."}
    if (t1 - t0).days > MAX_DAYS_EXT:
        return {"error": f"Rango máximo permitido: {MAX_DAYS_EXT} días."}
    if not feature_keys:
        return {"error": "feature_keys no puede estar vacío."}

    try:
        from src.db.store import get_conn

        conn = get_conn()
        placeholders = ",".join(["?"] * len(feature_keys))
        rows = conn.execute(
            f"""SELECT señal_id, fecha::text, valor
                FROM valores_señales
                WHERE ubicacion_id = ? AND señal_id IN ({placeholders})
                  AND fecha >= ? AND fecha <= ? AND valor IS NOT NULL
                ORDER BY señal_id, fecha""",
            [location_uuid] + feature_keys + [str(t0.date()), str(t1.date())],
        ).fetchall()
    except Exception as e:
        return {"error": f"Error al consultar features: {e}"}

    by_key: dict = {}
    for fk, fecha, val in rows:  # fk=señal_id, val=valor
        by_key.setdefault(fk, []).append({"fecha": fecha, "valor": round(float(val), 2)})

    yoy_deltas: dict = {}
    if incluir_yoy:
        t0_py = t0 - pd.DateOffset(years=1)
        t1_py = t1 - pd.DateOffset(years=1)
        try:
            from src.db.store import get_conn

            conn = get_conn()
            py_rows = conn.execute(
                f"""SELECT señal_id, SUM(valor)
                    FROM valores_señales
                    WHERE ubicacion_id = ? AND señal_id IN ({placeholders})
                      AND fecha >= ? AND fecha <= ? AND valor IS NOT NULL
                    GROUP BY señal_id""",
                [location_uuid] + feature_keys + [str(t0_py.date()), str(t1_py.date())],
            ).fetchall()
            py_totals = {r[0]: float(r[1]) for r in py_rows if r[1] is not None}
            for fk, vals in by_key.items():
                curr_total = sum(v["valor"] for v in vals)
                prev_total = py_totals.get(fk)
                if prev_total and prev_total != 0:
                    yoy_deltas[fk] = round((curr_total - prev_total) / prev_total * 100, 1)
        except Exception:
            pass

    resumen: dict = {}
    for fk, vals in by_key.items():
        valores = [v["valor"] for v in vals]
        entry: dict = {
            "total": round(sum(valores), 2),
            "media_dia": round(sum(valores) / len(valores), 2),
            "max": round(max(valores), 2),
            "min": round(min(valores), 2),
            "n_dias": len(valores),
        }
        if fk in yoy_deltas:
            entry["yoy_pct"] = yoy_deltas[fk]
        resumen[fk] = entry

    keys_sin_datos = [k for k in feature_keys if k not in by_key]
    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion": nombre,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "resumen": resumen,
        "series": by_key,
        "sin_datos": keys_sin_datos,
    }


# ── Herramienta 12: get_cruise_calls ─────────────────────────────────────────


def get_cruise_calls(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> dict:
    """
    Devuelve las escalas de cruceros en una ubicación portuaria: nombre del
    barco, operador, pasajeros y terminal. Incluye resumen mensual y
    comparativa YoY de pasajeros totales (si hay datos del año anterior).
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}

    try:
        import json as _json

        from src.db.store import get_conn

        conn = get_conn()
        raw_rows = conn.execute(
            """SELECT fecha_inicio::text, metadata
               FROM eventos
               WHERE ubicacion_id = ? AND evento_key = 'escala_crucero'
                 AND fecha_inicio >= ? AND fecha_inicio <= ?
               ORDER BY fecha_inicio""",
            [location_uuid, str(t0.date()), str(t1.date())],
        ).fetchall()
    except Exception as e:
        return {"error": f"No hay datos de cruceros para esta ubicación: {e}"}

    if not raw_rows:
        return {
            "ubicacion": (_find_location(location_uuid) or {}).get("name", location_uuid),
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
            "n_escalas": 0,
            "escalas": [],
            "nota": "No se registran escalas de cruceros en este periodo.",
        }

    escalas = []
    for fecha_s, meta_json in raw_rows:
        meta = (
            meta_json
            if isinstance(meta_json, dict)
            else (_json.loads(meta_json) if meta_json else {})
        )
        escalas.append(
            {
                "fecha": fecha_s,
                "barco": meta.get("barco", "—"),
                "operador": meta.get("operador") or meta.get("naviera", ""),
                "pasajeros": meta.get("n_pasajeros"),
                "terminal": meta.get("terminal", ""),
            }
        )

    # Resumen mensual
    df_e = pd.DataFrame(escalas)
    df_e["fecha"] = pd.to_datetime(df_e["fecha"])
    df_e["mes"] = df_e["fecha"].dt.to_period("M").astype(str)
    resumen_mensual = (
        df_e.groupby("mes")
        .agg(n_escalas=("barco", "count"), pasajeros=("pasajeros", "sum"))
        .reset_index()
        .rename(columns={"pasajeros": "pasajeros_totales"})
        .to_dict("records")
    )

    total_pax = int(df_e["pasajeros"].sum())

    # YoY: comparar con mismo período año anterior via store_features_ext
    yoy: dict | None = None
    try:
        from src.db.store import get_conn

        conn = get_conn()
        t0_py = t0 - pd.DateOffset(years=1)
        t1_py = t1 - pd.DateOffset(years=1)
        py_row = conn.execute(
            """SELECT SUM(valor) FROM valores_señales
               WHERE ubicacion_id = ? AND señal_id = 'n_pasajeros_crucero_dia'
                 AND fecha >= ? AND fecha <= ? AND valor IS NOT NULL""",
            [location_uuid, str(t0_py.date()), str(t1_py.date())],
        ).fetchone()
        if py_row and py_row[0]:
            prev_pax = float(py_row[0])
            yoy = {
                "periodo_anterior": {"inicio": str(t0_py.date()), "fin": str(t1_py.date())},
                "pasajeros_año_anterior": int(prev_pax),
                "delta_pct": (
                    round((total_pax - prev_pax) / prev_pax * 100, 1) if prev_pax else None
                ),
            }
    except Exception:
        pass

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    result: dict = {
        "ubicacion": nombre,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "n_escalas": len(escalas),
        "pasajeros_totales": total_pax,
        "resumen_mensual": resumen_mensual,
        "escalas": escalas,
    }
    if yoy:
        result["yoy"] = yoy
    return result


# ── Herramienta 13: get_model_metrics ────────────────────────────────────────


def get_model_metrics(
    location_uuid: str,
    zone_uuid: str | None = None,
) -> dict:
    """
    Devuelve métricas de calidad del modelo predictivo XGBoost y evaluación
    de features individuales para una ubicación/zona.

    NOTA: el modelo entrena on-demand (sin registro persistente). Para obtener
    WMAPE/MAE del modelo actual llama a get_forecast — devuelve métricas reales
    calculadas contra datos de validación del mismo entrenamiento.
    Esta herramienta devuelve los resultados de evaluación de features almacenados
    en evaluaciones_señales (si los hay).
    """
    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    feat_evals: list = []
    try:
        from src.db.store import get_conn

        conn = get_conn()
        q = """SELECT señal_id, fecha_eval_ini, fecha_eval_fin,
                      wmape_baseline, wmape_con_feat, wmape_delta, horizonte
               FROM evaluaciones_señales WHERE ubicacion_id = ?"""
        params: list = [location_uuid]
        if zone_uuid:
            q += " AND (indice_split IS NULL OR indice_split = 0)"
        q += " ORDER BY evaluado_en DESC LIMIT 50"
        for fk, fi, ff, wb, wf, wd, hz in conn.execute(q, params).fetchall():
            feat_evals.append(
                {
                    "feature_key": fk,
                    "periodo": f"{fi} → {ff}",
                    "wmape_baseline": round(float(wb), 3) if wb is not None else None,
                    "wmape_con_feat": round(float(wf), 3) if wf is not None else None,
                    "mejora_wmape_pct": round(float(wd) * 100, 2) if wd is not None else None,
                    "horizonte_dias": hz,
                }
            )
    except Exception:
        pass

    return {
        "ubicacion": nombre,
        "nota": (
            "El modelo entrena on-demand; no hay registro persistente de modelos. "
            "Llama a get_forecast para obtener WMAPE/MAE del modelo actual."
        ),
        "evaluacion_features": feat_evals,
        "n_evaluaciones_features": len(feat_evals),
    }


# ── Herramienta 15: get_dwell_profile ────────────────────────────────────────


def get_dwell_profile(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
    zone_uuid: str | None = None,
) -> dict:
    """
    Devuelve el perfil completo de permanencia y fidelización de visitantes
    para una ubicación en un rango de fechas.

    Permanencia (dwellTime):
      - media_estancia_seg: media del periodo (en segundos)
      - boxplot: distribución {min, Q1, mediana, Q3, max} del último día
        con datos — en minutos. Revela si la media está distorsionada por
        outliers (ej. Q1=1min, Q3=5min, max=11min con media aparente de 5min).

    Fidelización (frecuency histograms):
      Cuántos visitantes únicos vinieron 1 vez, 2 veces o 3+ en cada ventana:
      - frecuencia_7d, 28d, mes, anyo: {una_vez, dos_veces, tres_o_mas, pct_retorno}
      El pct_retorno = visitantes que volvieron al menos una vez / total únicos.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}
    if t1 < t0:
        return {"error": "fecha_inicio debe ser anterior a fecha_fin."}
    if (t1 - t0).days > MAX_DAYS:
        return {"error": f"Rango máximo: {MAX_DAYS} días."}

    try:
        from src.db.store import get_conn

        conn = get_conn()
        query = """
            SELECT fecha::text,
                   tiempo_estancia_min,
                   boxplot_estancia,
                   histograma_frecuencia_7d,
                   histograma_frecuencia_28d,
                   histograma_frecuencia_mes,
                   histograma_frecuencia_anyo
            FROM visitas
            WHERE ubicacion_id = ?
              AND fecha >= ? AND fecha <= ?
        """
        params: list = [location_uuid, str(t0.date()), str(t1.date())]
        if zone_uuid:
            query += " AND zona_id = ?"
            params.append(zone_uuid)
        query += " ORDER BY fecha DESC"
        rows = conn.execute(query, params).fetchall()
    except Exception as e:
        return {"error": f"Error al consultar datos de permanencia: {e}"}

    if not rows:
        return {"error": f"Sin datos para el rango {fecha_inicio}→{fecha_fin}."}

    # Media de estancia del periodo
    dwell_vals = [r[1] for r in rows if r[1] is not None]
    media_estancia = round(sum(dwell_vals) / len(dwell_vals), 1) if dwell_vals else None

    # Boxplot del día más reciente con datos
    boxplot_parsed = None
    for row in rows:
        raw = row[2]
        if raw:
            try:
                bp = json.loads(raw) if isinstance(raw, str) else raw
                if bp:
                    boxplot_parsed = {
                        "min_min": bp.get("min"),
                        "Q1_min": bp.get("Q1"),
                        "mediana_min": bp.get("median"),
                        "Q3_min": bp.get("Q3"),
                        "max_min": bp.get("max"),
                    }
                    break
            except Exception:
                pass

    def _parse_freq(raw) -> dict | None:
        if not raw:
            return None
        try:
            h = json.loads(raw) if isinstance(raw, str) else raw
            if not h:
                return None
            una = int(h.get("one", 0) or 0)
            dos = int(h.get("two", 0) or 0)
            tres = int(h.get("three_plus", 0) or 0)
            total = una + dos + tres
            return {
                "una_vez": una,
                "dos_veces": dos,
                "tres_o_mas": tres,
                "pct_retorno": round((dos + tres) / total * 100, 1) if total else None,
            }
        except Exception:
            return None

    # Toma el último día con histogramas de frecuencia
    freq_7d = freq_28d = freq_mes = freq_anyo = None
    for row in rows:
        if freq_7d is None:
            freq_7d = _parse_freq(row[3])
        if freq_28d is None:
            freq_28d = _parse_freq(row[4])
        if freq_mes is None:
            freq_mes = _parse_freq(row[5])
        if freq_anyo is None:
            freq_anyo = _parse_freq(row[6])
        if all(x is not None for x in [freq_7d, freq_28d, freq_mes, freq_anyo]):
            break

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    result: dict = {
        "ubicacion": nombre,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "dias_con_datos": len(rows),
        "media_estancia_min": int(media_estancia) if media_estancia else None,
    }
    if boxplot_parsed:
        result["boxplot_estancia_min"] = boxplot_parsed
    if freq_7d:
        result["fidelizacion_7d"] = freq_7d
    if freq_28d:
        result["fidelizacion_28d"] = freq_28d
    if freq_mes:
        result["fidelizacion_mes"] = freq_mes
    if freq_anyo:
        result["fidelizacion_anyo"] = freq_anyo

    return result


# ── Herramienta 16: get_funnel_ratios ────────────────────────────────────────


def get_funnel_ratios(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> dict:
    """
    Calcula los ratios de conversión del embudo Exterior→Interior→Checkout
    (Calle→Tienda→Caja) para una ubicación en un rango de fechas.

    Devuelve visitantes por tipo de zona, ratio Calle→Tienda, ratio Tienda→Caja
    y ratio global Calle→Caja. Incluye comparativa WoW (mismos días semana anterior)
    para cada ratio.

    Usa tipo_zona de la tabla zonas para clasificar: exterior, interior, checkout.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}
    if t1 < t0:
        return {"error": "La fecha de inicio debe ser anterior a la fecha de fin."}

    try:
        from src.db.store import get_conn

        conn = get_conn()
        rows = conn.execute(
            """
            SELECT z.tipo_zona, SUM(v.total_visitas) AS total
            FROM visitas v
            JOIN zonas z ON z.zona_id = v.zona_id
            WHERE v.ubicacion_id = ?
              AND v.fecha >= ? AND v.fecha <= ?
              AND z.oculta = FALSE
            GROUP BY z.tipo_zona
            """,
            [location_uuid, str(t0.date()), str(t1.date())],
        ).fetchall()
    except Exception as e:
        return {"error": f"Error al consultar datos: {e}"}

    if not rows:
        return {"error": f"Sin datos para el rango {fecha_inicio}→{fecha_fin}."}

    totals: dict[str, int] = {}
    for tipo, total in rows:
        if tipo:
            totals[tipo.lower()] = int(total or 0)

    ext = totals.get("exterior", 0)
    inte = totals.get("interior", 0)
    chk = totals.get("checkout", 0)

    def _ratio(num: int, den: int) -> float | None:
        return round(num / den * 100, 1) if den > 0 else None

    # WoW: mismos días semana anterior
    delta = (t1 - t0).days + 1
    t0_wow = t0 - pd.Timedelta(days=delta)
    t1_wow = t1 - pd.Timedelta(days=delta)
    wow: dict[str, int] = {}
    try:
        wow_rows = conn.execute(
            """
            SELECT z.tipo_zona, SUM(v.total_visitas) AS total
            FROM visitas v
            JOIN zonas z ON z.zona_id = v.zona_id
            WHERE v.ubicacion_id = ?
              AND v.fecha >= ? AND v.fecha <= ?
              AND z.oculta = FALSE
            GROUP BY z.tipo_zona
            """,
            [location_uuid, str(t0_wow.date()), str(t1_wow.date())],
        ).fetchall()
        for tipo, total in wow_rows:
            if tipo:
                wow[tipo.lower()] = int(total or 0)
    except Exception:
        pass

    ext_w = wow.get("exterior", 0)
    inte_w = wow.get("interior", 0)
    chk_w = wow.get("checkout", 0)

    r_calle_tienda = _ratio(inte, ext)
    r_tienda_caja = _ratio(chk, inte)
    r_calle_caja = _ratio(chk, ext)
    r_calle_tienda_wow = _ratio(inte_w, ext_w)
    r_tienda_caja_wow = _ratio(chk_w, inte_w)
    r_calle_caja_wow = _ratio(chk_w, ext_w)

    def _diff(now, prev):
        if now is not None and prev is not None:
            return round(now - prev, 1)
        return None

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion": nombre,
        "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
        "visitantes": {"exterior": ext, "interior": inte, "checkout": chk},
        "ratios": {
            "calle_tienda_pct": r_calle_tienda,
            "tienda_caja_pct": r_tienda_caja,
            "calle_caja_pct": r_calle_caja,
        },
        "wow": {
            "visitantes": {"exterior": ext_w, "interior": inte_w, "checkout": chk_w},
            "calle_tienda_pct": r_calle_tienda_wow,
            "tienda_caja_pct": r_tienda_caja_wow,
            "calle_caja_pct": r_calle_caja_wow,
            "diff_calle_tienda_pp": _diff(r_calle_tienda, r_calle_tienda_wow),
            "diff_tienda_caja_pp": _diff(r_tienda_caja, r_tienda_caja_wow),
            "diff_calle_caja_pp": _diff(r_calle_caja, r_calle_caja_wow),
        },
    }
