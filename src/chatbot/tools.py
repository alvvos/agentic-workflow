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

_DATA_DIR = Path(__file__).parent.parent / "data"
_RAW_GLOB = str(_DATA_DIR / "dataset_*.csv")
MAX_DAYS  = 90
MAX_DAYS_EXT = 760  # external features allow longer windows


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_location(location_uuid: str) -> dict | None:
    from src.db.queries import get_location_by_uuid, get_zones_for_loc
    loc = get_location_by_uuid(location_uuid)
    if loc is None:
        return None
    loc["zones"] = [
        {"uuid": z["zone_uuid"], "zoneName": z["nombre"], "hidden": z["hidden"], "zoneType": z["zone_type"]}
        for z in get_zones_for_loc(location_uuid)
    ]
    return loc


def _load_dataset(session_id: str = "local_dev") -> pd.DataFrame:
    try:
        from src.db.store import get_conn
        df = get_conn().execute("""
            SELECT fecha, location_uuid AS location_id, zone_uuid,
                   total_visits, unique_visitors, new_visitors,
                   dwell_time_min AS dwell_time, hourly_visits
            FROM fact_visitas ORDER BY fecha
        """).df()
        if not df.empty:
            df["fecha"] = pd.to_datetime(df["fecha"])
            return df
    except Exception:
        pass
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

    from src.services.ml_predictivo import ejecutar_auditoria_predictiva
    from src.db.queries import get_df_enriquecido
    from datetime import date

    df = get_df_enriquecido(location_uuid, session_id)

    if df is None or df.empty:
        # fallback CSV
        from src.data_processing.constructor_master import cargar_csv_crudo, enriquecer_datos_ubicacion
        archivo = str(_DATA_DIR / f"dataset_{session_id}.csv")
        if not Path(archivo).exists():
            files = sorted(glob(_RAW_GLOB))
            if not files:
                return {"error": "No hay datos disponibles."}
            archivo = files[-1]
        df_crudo = cargar_csv_crudo(archivo)
        if df_crudo is None or df_crudo.empty:
            return {"error": "No hay datos disponibles."}
        _ML_COLS = {"es_festivo", "llueve", "temp_max", "temp_min"}
        if _ML_COLS.issubset(df_crudo.columns):
            df = df_crudo[df_crudo["location_id"] == location_uuid].copy()
        else:
            df = enriquecer_datos_ubicacion(df_crudo, location_uuid)

    if df is None or df.empty:
        return {"error": f"Sin datos para la ubicación {location_uuid}."}

    falso_hoy = date.today().isoformat()
    result = ejecutar_auditoria_predictiva(df, location_uuid, zone_uuid, falso_hoy, n_dias)
    if "error" in result:
        return result

    grafica  = result.get("grafica", {})
    fechas   = grafica.get("fechas", [])
    predichos = grafica.get("predichos", [])
    reales   = grafica.get("reales", [])

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
        mask &= df["zone_uuid"] == zone_uuid
    sub = df[mask].copy()
    if sub.empty:
        return {"error": f"Sin datos para el rango {fecha_inicio}→{fecha_fin}."}

    agg = sub.groupby(["fecha", "zone_uuid"])["total_visits"].sum().reset_index()

    loc_info = _find_location(location_uuid)
    nombre = loc_info.get("name", location_uuid) if loc_info else location_uuid
    zone_map = {z["uuid"]: z["zoneName"] for z in (loc_info or {}).get("zones", [])}

    anomalias = []
    for zona, grp in agg.groupby("zone_uuid"):
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
                anomalias.append({
                    "fecha": row["fecha"].strftime("%Y-%m-%d"),
                    "zona": zone_map.get(zona, zona),
                    "visitas": int(row["total_visits"]),
                    "media_periodo": round(media, 1),
                    "z_score": round(float(z), 2),
                    "tipo": "pico" if z > 0 else "caída",
                })

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
        mask &= df["zone_uuid"] == zone_uuid
    sub = df[mask].dropna(subset=["hourly_visits"]).copy()
    if sub.empty:
        return {"error": "Sin datos de desglose horario en el periodo indicado."}

    _DIAS = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}

    rows = []
    for _, row in sub.iterrows():
        try:
            arr = json.loads(row["hourly_visits"]) if isinstance(row["hourly_visits"], str) else row["hourly_visits"]
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
        resultados.append({
            "nombre": nombre,
            "uuid": uuid,
            "total": total,
            "media_diaria": media_diaria,
            "dias_con_datos": int(sub["fecha"].nunique()),
        })

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
            """SELECT u.location_uuid, u.nombre, u.ciudad, u.provincia,
                      u.direccion, u.lat, u.lon, u.codigo_postal,
                      o.nombre AS org_nombre, o.org_uuid
               FROM dim_ubicaciones u
               JOIN dim_organizaciones o ON o.org_uuid = u.org_uuid
               WHERE u.location_uuid = ?""",
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
            """SELECT zone_uuid, nombre, zone_type, hidden, last_zone
               FROM dim_zonas WHERE location_uuid = ?
               ORDER BY sort_order NULLS LAST, nombre""",
            [location_uuid],
        ).fetchall()
    except Exception:
        zonas = []

    zonas_list = [
        {
            "uuid":       z[0],
            "nombre":     z[1],
            "tipo":       z[2],
            "oculta":     bool(z[3]),
            "zona_hoja":  bool(z[4]),
        }
        for z in zonas
    ]

    return {
        "location_uuid": location_uuid,
        "nombre":        nombre,
        "organizacion":  org_nombre,
        "org_uuid":      org_uuid,
        "ciudad":        ciudad,
        "provincia":     provincia,
        "direccion":     direccion,
        "codigo_postal": cp,
        "coordenadas":   {"lat": lat, "lon": lon},
        "n_zonas":       len(zonas_list),
        "zonas":         zonas_list,
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
            """SELECT f.feature_key, r.source, r.categoria, r.notas,
                      f.wmape_delta, f.evaluated_at
               FROM feature_flags f
               LEFT JOIN feature_registry r ON r.feature_key = f.feature_key
               WHERE f.location_uuid = ? AND f.status = 'active'
               ORDER BY r.categoria NULLS LAST, f.feature_key""",
            [location_uuid],
        ).fetchall()
    except Exception as e:
        return {"error": f"No se pudo consultar las features: {e}"}

    if not rows:
        loc = _find_location(location_uuid)
        nombre = loc.get("name", location_uuid) if loc else location_uuid
        return {
            "ubicacion":       nombre,
            "n_features_activas": 0,
            "features":        [],
            "nota":            "No hay features externas activas para esta ubicación.",
        }

    feature_keys = [r[0] for r in rows]
    last_values: dict = {}
    try:
        from src.db.store import get_conn
        conn = get_conn()
        placeholders = ",".join(["?"] * len(feature_keys))
        lv_rows = conn.execute(
            f"""SELECT feature_key, value, fecha::text
                FROM store_features_ext
                WHERE location_uuid = ? AND feature_key IN ({placeholders})
                  AND value IS NOT NULL
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
    for fk, source, categoria, notas, wmape_delta, evaluated_at in rows:
        entry: dict = {
            "feature_key": fk,
            "fuente":      source,
            "categoria":   categoria,
            "notas":       notas,
        }
        if wmape_delta is not None:
            entry["impacto_wmape_pct"] = round(float(wmape_delta) * 100, 2)
        if fk in last_values:
            entry["ultimo_valor"] = last_values[fk]["value"]
            entry["ultima_fecha"] = last_values[fk]["fecha"]
        features.append(entry)

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion":          nombre,
        "n_features_activas": len(features),
        "features":           features,
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
            f"""SELECT feature_key, fecha::text, value
                FROM store_features_ext
                WHERE location_uuid = ? AND feature_key IN ({placeholders})
                  AND fecha >= ? AND fecha <= ? AND value IS NOT NULL
                ORDER BY feature_key, fecha""",
            [location_uuid] + feature_keys + [str(t0.date()), str(t1.date())],
        ).fetchall()
    except Exception as e:
        return {"error": f"Error al consultar features: {e}"}

    by_key: dict = {}
    for fk, fecha, val in rows:
        by_key.setdefault(fk, []).append({"fecha": fecha, "valor": round(float(val), 2)})

    yoy_deltas: dict = {}
    if incluir_yoy:
        t0_py = t0 - pd.DateOffset(years=1)
        t1_py = t1 - pd.DateOffset(years=1)
        try:
            from src.db.store import get_conn
            conn = get_conn()
            py_rows = conn.execute(
                f"""SELECT feature_key, SUM(value)
                    FROM store_features_ext
                    WHERE location_uuid = ? AND feature_key IN ({placeholders})
                      AND fecha >= ? AND fecha <= ? AND value IS NOT NULL
                    GROUP BY feature_key""",
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
            "total":      round(sum(valores), 2),
            "media_dia":  round(sum(valores) / len(valores), 2),
            "max":        round(max(valores), 2),
            "min":        round(min(valores), 2),
            "n_dias":     len(valores),
        }
        if fk in yoy_deltas:
            entry["yoy_pct"] = yoy_deltas[fk]
        resumen[fk] = entry

    keys_sin_datos = [k for k in feature_keys if k not in by_key]
    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion":    nombre,
        "periodo":      {"inicio": fecha_inicio, "fin": fecha_fin},
        "resumen":      resumen,
        "series":       by_key,
        "sin_datos":    keys_sin_datos,
    }


# ── Herramienta 11: get_calendar_events ──────────────────────────────────────

def get_calendar_events(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
    evento_key: str | None = None,
) -> dict:
    """
    Devuelve los eventos del calendario externo de una ubicación en un rango
    de fechas: conciertos, festivales, partidos, cruceros, festivos, vacaciones,
    estrenos, manifestaciones, etc. Incluye título, impacto y tipo de evento.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}

    try:
        from src.db.store import get_conn
        conn = get_conn()
        query = """SELECT evento_key, fecha_inicio, fecha_fin, metadata
                   FROM store_calendario_org
                   WHERE location_uuid = ? AND fecha_fin >= ? AND fecha_inicio <= ?"""
        params: list = [location_uuid, str(t0.date()), str(t1.date())]
        if evento_key:
            query += " AND evento_key = ?"
            params.append(evento_key)
        query += " ORDER BY fecha_inicio"
        rows = conn.execute(query, params).fetchall()
    except Exception as e:
        return {"error": f"Error al consultar el calendario: {e}"}

    _META_KEYS = ("titulo", "nombre", "barco", "artista", "venue", "venue_nombre",
                  "aforo", "n_pasajeros", "pasajeros", "operador", "naviera",
                  "terminal", "rsvp_count", "going", "url", "impacto")

    eventos = []
    for key, fi, ff, meta_raw in rows:
        meta = meta_raw if isinstance(meta_raw, dict) else (
            json.loads(meta_raw) if meta_raw else {}
        )
        titulo = (meta.get("titulo") or meta.get("nombre") or
                  meta.get("barco") or key.replace("_", " ").title())
        entry: dict = {
            "evento_key":   key,
            "titulo":       titulo,
            "fecha_inicio": str(fi),
            "fecha_fin":    str(ff),
        }
        # Exponer toda la metadata relevante directamente
        for k in _META_KEYS:
            if k in meta and meta[k] is not None and k not in ("titulo", "nombre"):
                entry[k] = meta[k]
        eventos.append(entry)

    por_tipo: dict = {}
    for ev in eventos:
        por_tipo.setdefault(ev["evento_key"], 0)
        por_tipo[ev["evento_key"]] += 1

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion":   nombre,
        "periodo":     {"inicio": fecha_inicio, "fin": fecha_fin},
        "n_eventos":   len(eventos),
        "por_tipo":    por_tipo,
        "eventos":     eventos,
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
        from src.db.store import get_conn
        import json as _json
        conn = get_conn()
        raw_rows = conn.execute(
            """SELECT fecha_inicio::text, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND evento_key = 'escala_crucero'
                 AND fecha_inicio >= ? AND fecha_inicio <= ?
               ORDER BY fecha_inicio""",
            [location_uuid, str(t0.date()), str(t1.date())],
        ).fetchall()
    except Exception as e:
        return {"error": f"No hay datos de cruceros para esta ubicación: {e}"}

    if not raw_rows:
        return {
            "ubicacion": (_find_location(location_uuid) or {}).get("name", location_uuid),
            "periodo":   {"inicio": fecha_inicio, "fin": fecha_fin},
            "n_escalas": 0,
            "escalas":   [],
            "nota":      "No se registran escalas de cruceros en este periodo.",
        }

    escalas = []
    for fecha_s, meta_json in raw_rows:
        meta = meta_json if isinstance(meta_json, dict) else (_json.loads(meta_json) if meta_json else {})
        escalas.append({
            "fecha":     fecha_s,
            "barco":     meta.get('barco', '—'),
            "operador":  meta.get('operador') or meta.get('naviera', ''),
            "pasajeros": meta.get('n_pasajeros'),
            "terminal":  meta.get('terminal', ''),
        })

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
            """SELECT SUM(value) FROM store_features_ext
               WHERE location_uuid = ? AND feature_key = 'n_pasajeros_crucero_dia'
                 AND fecha >= ? AND fecha <= ? AND value IS NOT NULL""",
            [location_uuid, str(t0_py.date()), str(t1_py.date())],
        ).fetchone()
        if py_row and py_row[0]:
            prev_pax = float(py_row[0])
            yoy = {
                "periodo_anterior": {"inicio": str(t0_py.date()), "fin": str(t1_py.date())},
                "pasajeros_año_anterior": int(prev_pax),
                "delta_pct": round((total_pax - prev_pax) / prev_pax * 100, 1) if prev_pax else None,
            }
    except Exception:
        pass

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    result: dict = {
        "ubicacion":        nombre,
        "periodo":          {"inicio": fecha_inicio, "fin": fecha_fin},
        "n_escalas":        len(escalas),
        "pasajeros_totales": total_pax,
        "resumen_mensual":  resumen_mensual,
        "escalas":          escalas,
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
    Devuelve las métricas de precisión del modelo predictivo XGBoost para
    una ubicación/zona: WMAPE, MAE, fecha de entrenamiento, features usadas
    y resultados de evaluación de features individuales si están disponibles.
    """
    try:
        from src.db.store import get_conn
        conn = get_conn()
        query = """SELECT model_id, zone_uuid, trained_at, features, metrics, is_valid
                   FROM model_registry WHERE location_uuid = ?"""
        params: list = [location_uuid]
        if zone_uuid:
            query += " AND zone_uuid = ?"
            params.append(zone_uuid)
        query += " ORDER BY trained_at DESC LIMIT 10"
        model_rows = conn.execute(query, params).fetchall()
    except Exception as e:
        return {"error": f"No se pudo consultar el registro de modelos: {e}"}

    if not model_rows:
        loc = _find_location(location_uuid)
        nombre = loc.get("name", location_uuid) if loc else location_uuid
        return {
            "ubicacion": nombre,
            "modelos":   [],
            "nota":      "No hay modelos entrenados registrados para esta ubicación.",
        }

    modelos = []
    for mid, zuuid, trained_at, features_raw, metrics_raw, is_valid in model_rows:
        features = features_raw if isinstance(features_raw, list) else (
            json.loads(features_raw) if features_raw else []
        )
        metrics = metrics_raw if isinstance(metrics_raw, dict) else (
            json.loads(metrics_raw) if metrics_raw else {}
        )
        modelos.append({
            "model_id":   mid,
            "zone_uuid":  zuuid,
            "entrenado":  str(trained_at)[:10] if trained_at else None,
            "valido":     bool(is_valid),
            "n_features": len(features),
            "features":   features,
            "metricas":   metrics,
        })

    # Feature evaluation results
    feat_evals: list = []
    try:
        from src.db.store import get_conn
        conn = get_conn()
        q2 = """SELECT feature_key, fecha_eval_ini, fecha_eval_fin,
                       wmape_baseline, wmape_con_feat, wmape_delta, horizonte
                FROM feature_eval_results WHERE location_uuid = ?"""
        p2: list = [location_uuid]
        if zone_uuid:
            q2 += " AND (split_idx IS NULL OR split_idx = 0)"
        q2 += " ORDER BY evaluated_at DESC LIMIT 50"
        eval_rows = conn.execute(q2, p2).fetchall()
        for fk, fi, ff, wb, wf, wd, hz in eval_rows:
            feat_evals.append({
                "feature_key":      fk,
                "periodo":          f"{fi} → {ff}",
                "wmape_baseline":   round(float(wb), 3) if wb is not None else None,
                "wmape_con_feat":   round(float(wf), 3) if wf is not None else None,
                "mejora_wmape_pct": round(float(wd) * 100, 2) if wd is not None else None,
                "horizonte_dias":   hz,
            })
    except Exception:
        pass

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion":          nombre,
        "n_modelos":          len(modelos),
        "modelo_mas_reciente": modelos[0] if modelos else None,
        "todos_modelos":      modelos,
        "evaluacion_features": feat_evals,
    }


# ── Herramienta 14: get_ev_ranks ─────────────────────────────────────────────

def get_ev_ranks(
    location_uuid: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> dict:
    """
    Devuelve los scores diarios de presión de eventos externos (ev_rank_*)
    para una ubicación y rango de fechas.

    Los ev_ranks son señales 0-100 que cuantifican el impacto potencial de
    eventos sobre el tráfico de visitantes:
      - ev_rank_concierto:  presión por conciertos en el área
      - ev_rank_festival:   presión por festivales
      - ev_rank_deportivo:  presión por eventos deportivos
      - ev_rank_municipal:  presión por eventos municipales / culturales
      - ev_rank_total:      máximo de los anteriores (señal combinada)

    Útil para entender qué días tuvieron mayor contexto de eventos y
    correlacionar con anomalías de tráfico.
    """
    try:
        t0, t1 = pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin)
    except Exception:
        return {"error": "Formato de fecha no válido. Usa YYYY-MM-DD."}
    if t1 < t0:
        return {"error": "fecha_inicio debe ser anterior a fecha_fin."}
    if (t1 - t0).days > MAX_DAYS_EXT:
        return {"error": f"Rango máximo: {MAX_DAYS_EXT} días."}

    _EV_KEYS = [
        "ev_rank_concierto", "ev_rank_festival",
        "ev_rank_deportivo", "ev_rank_municipal", "ev_rank_total",
    ]

    try:
        from src.db.store import get_conn
        conn = get_conn()
        placeholders = ",".join(["?"] * len(_EV_KEYS))
        rows = conn.execute(
            f"""SELECT feature_key, fecha::text, value
                FROM store_features_ext
                WHERE location_uuid = ? AND feature_key IN ({placeholders})
                  AND fecha >= ? AND fecha <= ? AND value IS NOT NULL
                ORDER BY fecha, feature_key""",
            [location_uuid] + _EV_KEYS + [str(t0.date()), str(t1.date())],
        ).fetchall()
    except Exception as e:
        return {"error": f"Error al consultar ev_ranks: {e}"}

    # Agrupar por fecha
    by_date: dict[str, dict] = {}
    for fk, fecha, val in rows:
        by_date.setdefault(fecha, {})[fk] = round(float(val), 1)

    # Días con señal > 0
    dias_con_senal = [
        {"fecha": f, **scores}
        for f, scores in sorted(by_date.items())
        if any(v > 0 for v in scores.values())
    ]

    # Pico por tipología
    picos: dict = {}
    for fk in _EV_KEYS:
        vals = [(f, s[fk]) for f, s in by_date.items() if fk in s and s[fk] > 0]
        if vals:
            best = max(vals, key=lambda x: x[1])
            picos[fk] = {"fecha": best[0], "score": best[1]}

    loc = _find_location(location_uuid)
    nombre = loc.get("name", location_uuid) if loc else location_uuid

    return {
        "ubicacion":        nombre,
        "periodo":          {"inicio": fecha_inicio, "fin": fecha_fin},
        "n_dias_con_senal": len(dias_con_senal),
        "pico_por_tipo":    picos,
        "dias":             dias_con_senal,
    }
