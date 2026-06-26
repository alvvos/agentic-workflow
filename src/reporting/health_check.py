"""
Panel PM — Diagnóstico narrativo orientado al Product Manager.

Filosofía:
  • El Panel BI ya muestra los números. Este panel los INTERPRETA.
  • Cada sección responde una pregunta concreta del PM:
      1. ¿Cómo fue la semana?       → Narrativa con bullets
      2. ¿Qué zonas necesito mirar? → Tarjetas con semáforo + sparkline
      3. ¿Cuándo viene la gente?    → Distribución por día de la semana
      4. ¿Qué contexto tiene esta ubicación? → Panel geo Esri
  • Números solo cuando son imprescindibles para entender la frase.
  • Gráficos que ilustran una conclusión, no que presentan datos brutos.
"""

import json
import re
from datetime import date, timedelta

import dash_bootstrap_components as dbc
import holidays
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from src.core import data_master as _dm
from src.data_processing.data_radar import obtener_clima_historico, obtener_info_ubicacion
from src.data_processing.geo_enrichment import get_geo_snapshot_date, get_geo_vals
from src.reporting.geo_panel import generar_panel_geo_visual

festivos_espana = holidays.ES(years=[2024, 2025, 2026])
dias_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
dias_corto = ["L", "M", "X", "J", "V", "S", "D"]

_C_PRIMARY = "#0052CC"
_C_SUCCESS = "#28A745"
_C_DANGER = "#DC3545"
_C_AMBER = "#f39c12"
_C_DARK = "#2c3e50"
_C_MUTED = "#6c757d"
_CFG_GRAPH = {"displayModeBar": False, "responsive": True}


# ── Zone helpers ──────────────────────────────────────────────────────────────

_PALETA_PM = [
    "#0052CC",
    "#E67E22",
    "#27AE60",
    "#8E44AD",
    "#E74C3C",
    "#17A2B8",
    "#F39C12",
    "#2ECC71",
    "#9B59B6",
    "#C0392B",
    "#1ABC9C",
    "#D35400",
    "#2980B9",
    "#16A085",
    "#7D3C98",
]


def _color_zona(zona):
    zl = str(zona).lower()
    if "caja" in zl:
        return "#8e44ad"
    if "tienda" in zl:
        return "#e67e22"
    if "calle" in zl or "exterior" in zl:
        return "#2980b9"
    return _PALETA_PM[hash(zona) % len(_PALETA_PM)]


def _zona_meta(zona):
    """Returns (badge_label, icon_cls, tooltip)."""
    zl = str(zona).lower()
    if "caja" in zl:
        return (
            "Cierre de venta",
            "fas fa-cash-register",
            "Zona de caja — tráfico vinculado directamente a la conversión en compra.",
        )
    if "tienda" in zl:
        return (
            "Conversión",
            "fas fa-store",
            "Zona interior — indica qué proporción del tráfico exterior accede al establecimiento.",
        )
    if "calle" in zl or "exterior" in zl:
        return (
            "Captación",
            "fas fa-walking",
            "Zona exterior — tráfico peatonal registrado frente al establecimiento.",
        )
    return ("Analítica", "fas fa-layer-group", "Zona de medición de tráfico.")


# ── Data helpers ──────────────────────────────────────────────────────────────


def obtener_zonas_validas(ruta=None):
    try:
        from src.db.store import get_conn

        rows = (
            get_conn()
            .execute(
                "SELECT nombre FROM dim_zonas WHERE zone_type = 'last_zone' AND hidden = FALSE"
            )
            .fetchall()
        )
        return {r[0] for r in rows}
    except Exception:
        return set()


def formatear_fecha(fecha_obj):
    return f"{dias_semana_es[fecha_obj.weekday()]} {fecha_obj.strftime('%d/%m')}"


def calcular_delta(actual, anterior):
    if not anterior or pd.isna(anterior):
        return 0
    return (actual - anterior) / anterior * 100


def evaluar_periodo_zona(df_zona, fecha_max, dias_ventana):
    fmin = fecha_max - timedelta(days=dias_ventana - 1)
    fmax = fecha_max
    fmin_a = fmin - timedelta(days=dias_ventana)
    fmax_a = fmin - timedelta(days=1)

    dp = df_zona[(df_zona["fecha_dt"] >= fmin) & (df_zona["fecha_dt"] <= fmax)]
    da = df_zona[(df_zona["fecha_dt"] >= fmin_a) & (df_zona["fecha_dt"] <= fmax_a)]

    def _dwell(df):
        if "dwell_time" not in df.columns or df.empty:
            return 0.0
        m = df["dwell_time"].mean()
        return 0.0 if pd.isna(m) else m / 60

    res = {
        "visitantes": int(dp["unique_visitors"].sum()) if "unique_visitors" in dp.columns else 0,
        "estancia": _dwell(dp),
    }
    ant = {
        "visitantes": int(da["unique_visitors"].sum()) if "unique_visitors" in da.columns else 0,
        "estancia": _dwell(da),
    }

    dias_act = (
        dp.groupby("fecha_dt")["unique_visitors"].sum().reset_index()
        if "unique_visitors" in dp.columns
        else pd.DataFrame()
    )

    return res, ant, {k: calcular_delta(res[k], ant[k]) for k in res}, fmin, fmax, dias_act


def _slug(text):
    return re.sub(r"[^a-z0-9]", "-", str(text).lower())[:20]


def _pct_activos(df_zona, fmin, fmax):
    """Fracción de días en [fmin, fmax] con unique_visitors > 0."""
    n_dias = max((fmax - fmin).days + 1, 1)
    if df_zona.empty or "unique_visitors" not in df_zona.columns:
        return 0.0
    activos = df_zona[
        (df_zona["fecha_dt"] >= fmin)
        & (df_zona["fecha_dt"] <= fmax)
        & (df_zona["unique_visitors"] > 0)
    ]["fecha_dt"].nunique()
    return activos / n_dias


# ── Chart builders ────────────────────────────────────────────────────────────


def _fig_sparkline(dias_28, color):
    """Línea de tendencia de 28 días — sin ejes, sin etiquetas, solo la forma."""
    if dias_28 is None or dias_28.empty:
        return None
    df = dias_28.sort_values("fecha_dt")
    # NaN-aware: zeros are sensor outage days, treat as missing data
    y_raw = df["unique_visitors"].values.astype(float)
    valid = ~np.isnan(y_raw)
    if valid.sum() < 3:
        return None

    x_num = np.arange(len(y_raw))
    # Trend calculated only on valid (non-gap) points
    coef = np.polyfit(x_num[valid], y_raw[valid], 1)
    trend = np.polyval(coef, x_num)
    trend_color = _C_SUCCESS if coef[0] >= 0 else _C_DANGER

    fig = go.Figure()
    # Área rellena debajo de la línea real — connectgaps=False shows sensor gaps
    fig.add_trace(
        go.Scatter(
            x=list(x_num),
            y=y_raw.tolist(),
            mode="lines",
            connectgaps=False,
            line=dict(color=color, width=1.5, shape="spline"),
            fill="tozeroy",
            fillcolor="rgba(0,0,0,0.04)",
            hoverinfo="skip",
        )
    )
    # Línea de tendencia punteada
    fig.add_trace(
        go.Scatter(
            x=list(x_num),
            y=trend.tolist(),
            mode="lines",
            line=dict(color=trend_color, width=1.2, dash="dot"),
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        height=68,
        margin=dict(t=4, b=4, l=4, r=4, pad=0),
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, rangemode="tozero"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _fig_dias_semana(df_todas_zonas, fecha_max, dias=28):
    """Distribución por día de la semana — período actual (sólido) vs anterior (translúcido)."""
    if df_todas_zonas.empty or "unique_visitors" not in df_todas_zonas.columns:
        return None

    fmin_act = fecha_max - timedelta(days=dias - 1)
    fmin_ant = fmin_act - timedelta(days=dias)
    fmax_ant = fmin_act - timedelta(days=1)

    def _por_dia_semana(fmin, fmax):
        df = df_todas_zonas[
            (df_todas_zonas["fecha_dt"] >= fmin) & (df_todas_zonas["fecha_dt"] <= fmax)
        ].copy()
        if df.empty:
            return pd.Series([0.0] * 7, index=range(7))
        df["dia_sem"] = pd.to_datetime(df["fecha_dt"]).dt.dayofweek
        return (
            df.groupby(["fecha_dt", "dia_sem"])["unique_visitors"]
            .sum()
            .reset_index()
            .groupby("dia_sem")["unique_visitors"]
            .mean()
            .reindex(range(7), fill_value=0)
        )

    vals_act = _por_dia_semana(fmin_act, fecha_max)
    vals_ant = _por_dia_semana(fmin_ant, fmax_ant)

    if vals_act.sum() == 0:
        return None

    max_v = max(vals_act.max(), vals_ant.max()) or 1
    ratios = vals_act.values / max_v
    bar_colors = [f"rgba(0,82,204,{0.22 + 0.68 * r:.2f})" for r in ratios]
    peak_idx = int(np.argmax(vals_act.values))
    text_labels = [
        f"<b>{int(v):,}</b>" if i == peak_idx else "" for i, v in enumerate(vals_act.values)
    ]

    fig = go.Figure()
    if vals_ant.sum() > 0:
        fig.add_trace(
            go.Bar(
                x=dias_corto,
                y=vals_ant.values,
                marker=dict(
                    color="rgba(0,82,204,0.14)",
                    line=dict(color="rgba(0,82,204,0.35)", width=1),
                    cornerradius=5,
                ),
                hovertemplate="Anterior · %{x}: <b>%{y:,.0f}</b> visit./día<extra></extra>",
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Bar(
            x=dias_corto,
            y=vals_act.values,
            marker=dict(color=bar_colors, line=dict(width=0), cornerradius=5),
            text=text_labels,
            textposition="outside",
            textfont=dict(size=11, color=_C_DARK),
            hovertemplate="Actual · %{x}: <b>%{y:,.0f}</b> visit./día<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=165,
        barmode="group",
        margin=dict(t=16, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.38]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.25,
        bargroupgap=0.06,
    )
    return fig


def _fig_finde_vs_laborable(df_todas_zonas, fecha_max, dias=28):
    """Promedio visitantes/día: entre semana vs fin de semana — actual (sólido) vs anterior (translúcido)."""
    if df_todas_zonas.empty or "unique_visitors" not in df_todas_zonas.columns:
        return None

    fmin_act = fecha_max - timedelta(days=dias - 1)
    fmin_ant = fmin_act - timedelta(days=dias)
    fmax_ant = fmin_act - timedelta(days=1)

    def _avg_tipo(fmin, fmax):
        df = df_todas_zonas[
            (df_todas_zonas["fecha_dt"] >= fmin) & (df_todas_zonas["fecha_dt"] <= fmax)
        ].copy()
        if df.empty:
            return {"Entre semana": 0.0, "Fin de semana": 0.0}
        df["dia_sem"] = pd.to_datetime(df["fecha_dt"]).dt.dayofweek
        df["tipo"] = df["dia_sem"].apply(lambda x: "Fin de semana" if x >= 5 else "Entre semana")
        por_dia = df.groupby(["fecha_dt", "tipo"])["unique_visitors"].sum().reset_index()
        avg = por_dia.groupby("tipo")["unique_visitors"].mean()
        return {t: float(avg.get(t, 0)) for t in ["Entre semana", "Fin de semana"]}

    avg_act = _avg_tipo(fmin_act, fecha_max)
    avg_ant = _avg_tipo(fmin_ant, fmax_ant)

    tipos = ["Entre semana", "Fin de semana"]
    vals_act = [avg_act.get(t, 0) for t in tipos]
    vals_ant = [avg_ant.get(t, 0) for t in tipos]

    if max(vals_act) == 0:
        return None

    max_v = max(max(vals_act), max(vals_ant)) or 1
    colors_act = [_C_PRIMARY, "#e67e22"]
    colors_ant = ["rgba(0,82,204,0.15)", "rgba(230,126,34,0.15)"]
    border_ant = [_C_PRIMARY, "#e67e22"]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=tipos,
            y=vals_ant,
            marker=dict(color=colors_ant, line=dict(color=border_ant, width=1), cornerradius=5),
            hovertemplate="Anterior · %{x}: <b>%{y:,.0f}</b> visit./día<extra></extra>",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Bar(
            x=tipos,
            y=vals_act,
            marker=dict(color=colors_act, line=dict(width=0), cornerradius=5),
            text=[f"{v:,.0f}" for v in vals_act],
            textposition="outside",
            textfont=dict(size=12, color=_C_DARK),
            hovertemplate="Actual · %{x}: <b>%{y:,.0f}</b> visit./día<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        barmode="group",
        height=180,
        margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.40]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.25,
        bargroupgap=0.06,
    )
    return fig


def _fig_dwell_zonas(zonas_data, child_zones=None):
    """Tiempo medio de permanencia por zona — solo zonas padre."""
    _cz = child_zones or set()
    data = [
        (z["zona"], z["r"]["estancia"], _color_zona(z["zona"]))
        for z in zonas_data
        if z["r"]["estancia"] > 0 and z["zona"] not in _cz
    ]
    if not data:
        return None
    data.sort(key=lambda x: x[1], reverse=True)
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    colors = [d[2] for d in data]
    max_v = max(values)
    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=colors, line=dict(width=0), cornerradius=5),
            text=[f"{v:.1f} min" for v in values],
            textposition="outside",
            constraintext="none",
            textfont=dict(size=11, color=_C_DARK),
            hovertemplate="%{y}: <b>%{x:.1f} min</b> promedio<extra></extra>",
        )
    )
    fig.update_layout(
        height=180,
        margin=dict(t=8, b=8, l=8, r=52),
        xaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.5]),
        yaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.40,
    )
    return fig


def _fig_embudo_conversion(zonas_data):
    """
    Embudo exterior → tienda → caja con tasa de conversión entre pasos.
    Requiere al menos dos zonas con roles distintos identificables.
    """

    def _rol(z):
        zl = z["zona"].lower()
        if "exterior" in zl or "calle" in zl:
            return 0
        if "tienda" in zl:
            return 1
        if "caja" in zl:
            return 2
        return 99

    pasos = sorted([z for z in zonas_data if _rol(z) < 99], key=_rol)
    if len(pasos) < 2:
        return None
    values = [max(z["r"]["visitantes"], 0) for z in pasos]
    if max(values) == 0:
        return None

    labels = [z["zona"] for z in pasos]
    colors = [_color_zona(z["zona"]) for z in pasos]
    texts = []
    for i, v in enumerate(values):
        if i == 0:
            texts.append(f"<b>{v:,.0f}</b>")
        else:
            pct = v / (values[i - 1] or 1) * 100
            texts.append(f"<b>{v:,.0f}</b>  ·  {pct:.0f}% del paso anterior")

    max_v = max(values)
    fig = go.Figure()
    for lbl, val, col, txt in zip(labels, values, colors, texts):
        fig.add_trace(
            go.Bar(
                y=[lbl],
                x=[val],
                orientation="h",
                marker=dict(color=col, line=dict(width=0), cornerradius=5),
                text=[txt],
                textposition="outside",
                constraintext="none",
                textfont=dict(size=11, color=_C_DARK),
                hovertemplate=f"{lbl}: <b>%{{x:,.0f}}</b> visitantes<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_layout(
        height=180,
        margin=dict(t=8, b=8, l=8, r=8),
        xaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.65]),
        yaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        barmode="group",
        bargap=0.40,
    )
    return fig


# ── Narrative engine ──────────────────────────────────────────────────────────


def _eventos_narrativa(location_uuid: str, fecha_ini, fecha_max) -> dict:
    """
    Query store_calendario_org for high-impact events in period + next 28d.
    Returns {'pasados_alto': [...], 'proximos_alto': [...]}.
    """
    if not location_uuid:
        return {"pasados_alto": [], "proximos_alto": []}
    try:
        from src.db.store import get_conn

        conn = get_conn()
        hasta = fecha_max + timedelta(days=28)
        rows = conn.execute(
            """SELECT evento_key, fecha_inicio, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND fecha_inicio >= ? AND fecha_inicio <= ?
               ORDER BY fecha_inicio""",
            [
                location_uuid,
                str(fecha_ini.date() if hasattr(fecha_ini, "date") else fecha_ini),
                str(hasta.date() if hasattr(hasta, "date") else hasta),
            ],
        ).fetchall()
    except Exception:
        return {"pasados_alto": [], "proximos_alto": []}

    hoy = fecha_max.date() if hasattr(fecha_max, "date") else fecha_max
    pasados, proximos = [], []
    for key, fi, meta_json in rows:
        fi_d = pd.to_datetime(fi).date()
        meta = (
            meta_json
            if isinstance(meta_json, dict)
            else (json.loads(meta_json) if meta_json else {})
        )

        # Impacto explícito (fuentes legacy/mock) o inferido desde señales de cada source
        impacto = meta.get("impacto")
        if not impacto:
            # Ticketmaster events are real ticketed events — always notable
            if key.startswith("tm_") or key in (
                "concierto_wizink",
                "festival_madrid",
                "partido_deportivo",
                "estreno_callao",
                "manifestacion_gran_via",
            ):
                impacto = "alto"
            else:
                aforo = meta.get("aforo") or 0
                rsvp = meta.get("rsvp_count") or 0
                going = meta.get("going") or 0
                if aforo > 5_000 or rsvp > 500 or going > 100:
                    impacto = "alto"
                elif aforo > 1_000 or rsvp > 100 or going > 30:
                    impacto = "medio"
        if impacto != "alto":
            continue

        nombre = meta.get("nombre") or meta.get("titulo") or key.replace("_", " ").title()
        artista = meta.get("artista") or ""
        titulo = f"{nombre} — {artista}" if artista else nombre
        ev = {"titulo": titulo, "fecha": fi_d}
        (pasados if fi_d <= hoy else proximos).append(ev)

    # Cruceros desde store_calendario_org (evento_key = 'escala_crucero')
    cruceros: list[dict] = []
    try:
        fi_str = str(fecha_ini.date() if hasattr(fecha_ini, "date") else fecha_ini)
        hasta_str = str(hasta.date() if hasattr(hasta, "date") else hasta)
        cr_rows = conn.execute(
            """SELECT fecha_inicio::text, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND evento_key = 'escala_crucero'
                 AND fecha_inicio >= ? AND fecha_inicio <= ?
               ORDER BY fecha_inicio""",
            [location_uuid, fi_str, hasta_str],
        ).fetchall()
        for fecha_s, meta_json in cr_rows:
            meta = (
                meta_json
                if isinstance(meta_json, dict)
                else (json.loads(meta_json) if meta_json else {})
            )
            cruceros.append(
                {
                    "fecha": pd.to_datetime(fecha_s).date(),
                    "nombre_barco": meta.get("barco") or "—",
                    "n_pasajeros": int(meta.get("n_pasajeros") or 0),
                }
            )
    except Exception:
        pass

    return {"pasados_alto": pasados, "proximos_alto": proximos, "cruceros": cruceros}


def _narrativa(
    zonas_data, fecha_max, clima, ventana="semana", geo_vals=None, location_uuid=None, eventos=None
):
    """
    Returns list of (categoria, nivel, icon_cls, texto).
    Categorías: trafico | experiencia | integridad | clima | eventos
    """
    items = []
    periodo = "mes" if ventana == "mes" else "semana"
    periodo_ant = "el mes" if ventana == "mes" else "la semana"
    dias_v = 28 if ventana == "mes" else 7

    total_p = sum(z["r"]["visitantes"] for z in zonas_data)
    total_p_a = sum(z["a"]["visitantes"] for z in zonas_data)
    dg = calcular_delta(total_p, total_p_a)

    def _add(cat, level, icon, text):
        items.append((cat, level, icon, text))

    # ── AFLUENCIA ────────────────────────────────────────────────────────────

    if dg >= 10:
        _add(
            "trafico",
            "success",
            "fas fa-arrow-trend-up",
            f"El volumen total de tráfico alcanzó {total_p:,} visitas durante el {periodo} analizado, "
            f"frente a {total_p_a:,} registradas en el {periodo_ant} precedente. "
            f"Incremento del {dg:.0f}%.",
        )
    elif dg <= -10:
        _add(
            "trafico",
            "danger",
            "fas fa-arrow-trend-down",
            f"El volumen total de tráfico registró {total_p:,} visitas durante el {periodo} analizado, "
            f"frente a {total_p_a:,} en el {periodo_ant} precedente. "
            f"Descenso del {abs(dg):.0f}%.",
        )
    else:
        _add(
            "trafico",
            "secondary",
            "fas fa-equals",
            f"El volumen total de tráfico se mantuvo estable: {total_p:,} visitas en el {periodo} analizado "
            f"frente a {total_p_a:,} en el {periodo_ant} precedente ({dg:+.1f}%).",
        )

    all_dias = (
        pd.concat(
            [z["dias_p"] for z in zonas_data if not z["dias_p"].empty],
            ignore_index=True,
        )
        if any(not z["dias_p"].empty for z in zonas_data)
        else pd.DataFrame()
    )

    if not all_dias.empty:
        agg = all_dias.groupby("fecha_dt")["unique_visitors"].sum().reset_index()
        peak = agg.loc[agg["unique_visitors"].idxmax()]
        trough = agg.loc[agg["unique_visitors"].idxmin()]
        _add(
            "trafico",
            "primary",
            "fas fa-calendar-day",
            f"El {formatear_fecha(peak['fecha_dt'])} fue la jornada de mayor afluencia del {periodo}, "
            f"con {int(peak['unique_visitors']):,} visitas registradas.",
        )
        if (
            peak["unique_visitors"] > 0
            and (trough["unique_visitors"] / peak["unique_visitors"]) < 0.65
        ):
            _add(
                "trafico",
                "secondary",
                "fas fa-calendar-minus",
                f"El día de menor afluencia fue el {formatear_fecha(trough['fecha_dt'])}, "
                f"con {int(trough['unique_visitors']):,} visitas, "
                f"un {(1 - trough['unique_visitors']/peak['unique_visitors'])*100:.0f}% "
                f"por debajo del pico del {periodo}.",
            )

    dias_28_data = [z["dias_28"] for z in zonas_data if not z["dias_28"].empty]
    if dias_28_data:
        try:
            dias_28_all = pd.concat(dias_28_data, ignore_index=True)
            dias_28_agg = dias_28_all.groupby("fecha_dt")["unique_visitors"].sum().reset_index()
            fmin_act_v = fecha_max - timedelta(days=dias_v - 1)
            fmin_ant_v = fmin_act_v - timedelta(days=dias_v)
            act_vals = dias_28_agg[dias_28_agg["fecha_dt"] >= fmin_act_v][
                "unique_visitors"
            ].dropna()
            ant_vals = dias_28_agg[
                (dias_28_agg["fecha_dt"] >= fmin_ant_v) & (dias_28_agg["fecha_dt"] < fmin_act_v)
            ]["unique_visitors"].dropna()
            if (
                len(act_vals) >= 3
                and len(ant_vals) >= 3
                and act_vals.mean() > 0
                and ant_vals.mean() > 0
            ):
                cv_act = act_vals.std() / act_vals.mean() * 100
                cv_ant = ant_vals.std() / ant_vals.mean() * 100
                if cv_act > cv_ant * 1.25:
                    _add(
                        "trafico",
                        "warning",
                        "fas fa-wave-square",
                        f"El tráfico diario mostró mayor variabilidad durante el {periodo} analizado "
                        f"(dispersión {cv_act:.0f}%) que en el {periodo_ant} precedente ({cv_ant:.0f}%). "
                        f"Los picos y valles fueron más pronunciados.",
                    )
                elif cv_act < cv_ant * 0.75:
                    _add(
                        "trafico",
                        "success",
                        "fas fa-wave-square",
                        f"El tráfico diario fue más homogéneo durante el {periodo} analizado "
                        f"(dispersión {cv_act:.0f}%) que en el {periodo_ant} precedente ({cv_ant:.0f}%). "
                        f"La distribución de visitas fue más estable.",
                    )
        except Exception:
            pass

    zonas_con_delta = [
        z for z in zonas_data if z["r"]["visitantes"] > 0 and abs(z["d"]["visitantes"]) >= 8
    ]
    if zonas_con_delta:
        mejor = max(zonas_con_delta, key=lambda z: z["d"]["visitantes"])
        peor = min(zonas_con_delta, key=lambda z: z["d"]["visitantes"])
        if mejor["d"]["visitantes"] >= 8:
            _add(
                "trafico",
                "success",
                "fas fa-trophy",
                f"La zona de mayor crecimiento relativo durante el {periodo} fue «{mejor['zona']}», "
                f"con {mejor['r']['visitantes']:,} visitas frente a {mejor['a']['visitantes']:,} "
                f"en el {periodo_ant} precedente ({mejor['d']['visitantes']:+.0f}%).",
            )
        if peor["d"]["visitantes"] <= -8 and peor["zona"] != mejor["zona"]:
            _add(
                "trafico",
                "danger",
                "fas fa-arrow-down-wide-short",
                f"La zona con mayor caída relativa fue «{peor['zona']}», "
                f"con {peor['r']['visitantes']:,} visitas frente a {peor['a']['visitantes']:,} "
                f"en el {periodo_ant} precedente ({peor['d']['visitantes']:+.0f}%). "
                f"Se recomienda analizar si la variación responde a una incidencia puntual "
                f"o a una tendencia sostenida.",
            )

    # ── EXPERIENCIA ──────────────────────────────────────────────────────────

    est_p = sum(z["r"]["estancia"] * max(z["r"]["visitantes"], 1) for z in zonas_data) / max(
        total_p, 1
    )
    est_p_a = sum(z["a"]["estancia"] * max(z["a"]["visitantes"], 1) for z in zonas_data) / max(
        total_p_a, 1
    )
    d_est = calcular_delta(est_p, est_p_a)

    if est_p > 0 and abs(d_est) >= 6:
        if d_est > 0:
            _add(
                "experiencia",
                "success",
                "fas fa-clock",
                f"El tiempo medio de permanencia se situó en {est_p:.1f} min durante el {periodo}, "
                f"frente a {est_p_a:.1f} min en el {periodo_ant} precedente. "
                f"Incremento del {d_est:.0f}%.",
            )
        else:
            _add(
                "experiencia",
                "warning",
                "fas fa-clock",
                f"El tiempo medio de permanencia descendió a {est_p:.1f} min durante el {periodo}, "
                f"frente a {est_p_a:.1f} min del {periodo_ant} precedente "
                f"(variación de {d_est:.0f}%). Se recomienda analizar los factores "
                f"que puedan estar reduciendo la duración de las visitas.",
            )

    for z in zonas_data:
        zn = z["zona"]
        zl = zn.lower()
        dv = z["d"]["visitantes"]
        rv = z["r"]["visitantes"]
        av = z["a"]["visitantes"]

        if "exterior" in zl or "calle" in zl:
            if dv <= -20:
                _add(
                    "experiencia",
                    "warning",
                    "fas fa-walking",
                    f"La zona exterior «{zn}» registró {rv:,} visitas en el {periodo} analizado, "
                    f"frente a {av:,} en el {periodo_ant} precedente (descenso del {abs(dv):.0f}%). "
                    f"Se recomienda verificar la existencia de factores externos: obras, "
                    f"cortes de calle o condiciones meteorológicas adversas.",
                )
        elif "tienda" in zl:
            ext = next(
                (
                    z2
                    for z2 in zonas_data
                    if "exterior" in z2["zona"].lower() or "calle" in z2["zona"].lower()
                ),
                None,
            )
            if ext:
                ext_dv = ext["d"]["visitantes"]
                ext_rv = ext["r"]["visitantes"]
                if dv <= -15 and ext_dv > -5:
                    _add(
                        "experiencia",
                        "danger",
                        "fas fa-store",
                        f"El tráfico exterior se mantuvo estable ({ext_rv:,} visitas), "
                        f"mientras la zona interior «{zn}» registró {rv:,} visitas frente a "
                        f"{av:,} en el {periodo_ant} precedente (descenso del {abs(dv):.0f}%). "
                        f"Se recomienda revisar los elementos de conversión: escaparate, "
                        f"señalética y disposición del acceso.",
                    )
                elif dv >= 15 and ext_dv < 5:
                    _add(
                        "experiencia",
                        "success",
                        "fas fa-store",
                        f"La zona interior «{zn}» alcanzó {rv:,} visitas frente a {av:,} en el "
                        f"{periodo_ant} precedente (incremento del {dv:.0f}%), con el tráfico exterior "
                        f"estable. Esto indica una mejora en la tasa de conversión del paso peatonal.",
                    )
            elif dv <= -15:
                _add(
                    "experiencia",
                    "danger",
                    "fas fa-store",
                    f"La zona interior «{zn}» registró {rv:,} visitas durante el {periodo} analizado, "
                    f"frente a {av:,} en el {periodo_ant} precedente (descenso del {abs(dv):.0f}%).",
                )
        elif "caja" in zl:
            if dv <= -15:
                _add(
                    "experiencia",
                    "danger",
                    "fas fa-cash-register",
                    f"La zona de caja «{zn}» registró {rv:,} visitas en el {periodo} analizado, "
                    f"frente a {av:,} en el {periodo_ant} precedente (descenso del {abs(dv):.0f}%). "
                    f"Se recomienda contrastar con el tráfico interior para determinar si la variación "
                    f"obedece a una menor conversión o a una caída general de afluencia.",
                )
            elif dv >= 15:
                _add(
                    "experiencia",
                    "success",
                    "fas fa-cash-register",
                    f"La zona de caja «{zn}» alcanzó {rv:,} visitas en el {periodo} analizado, "
                    f"frente a {av:,} en el {periodo_ant} precedente "
                    f"(incremento del {dv:.0f}%).",
                )

    # ── INTEGRIDAD ──────────────────────────────────────────────────────────

    for z in zonas_data:
        zn = z["zona"]
        if z.get("gap_actual"):
            _add(
                "integridad",
                "warning",
                "fas fa-wifi",
                f"La zona «{zn}» presenta días sin datos en el {periodo} actual. "
                f"Es posible que el nodo de captura haya estado temporalmente inactivo. "
                f"Los datos disponibles son parciales y la comparativa podría no ser representativa.",
            )
        elif z.get("gap_anterior"):
            _add(
                "integridad",
                "info",
                "fas fa-circle-exclamation",
                f"El período de comparación de la zona «{zn}» incluye días sin datos registrados "
                f"(incidencia previa en el nodo de captura). La variación indicada "
                f"({z['d']['visitantes']:+.0f}%) puede estar sobreestimada.",
            )

    # ── CLIMA ────────────────────────────────────────────────────────────────

    if clima:
        fmin_clima = fecha_max - timedelta(days=dias_v - 1)
        fmin_ant_c = fmin_clima - timedelta(days=dias_v)
        fmax_ant_c = fmin_clima - timedelta(days=1)
        s_act = fmin_clima.strftime("%Y-%m-%d")
        s_ant = fmin_ant_c.strftime("%Y-%m-%d")
        s_ant_max = fmax_ant_c.strftime("%Y-%m-%d")

        dias_act = {k: v for k, v in clima.items() if s_act <= k <= fecha_max.strftime("%Y-%m-%d")}
        dias_ant = {k: v for k, v in clima.items() if s_ant <= k <= s_ant_max}

        tmaxes_act = [v["tmax"] for v in dias_act.values() if v.get("tmax") is not None]
        tmaxes_ant = [v["tmax"] for v in dias_ant.values() if v.get("tmax") is not None]

        if tmaxes_act and tmaxes_ant:
            avg_act = sum(tmaxes_act) / len(tmaxes_act)
            avg_ant = sum(tmaxes_ant) / len(tmaxes_ant)
            diff = avg_act - avg_ant
            if abs(diff) >= 2:
                mas_menos = "más cálido" if diff > 0 else "más frío"
                nivel = "warning" if diff >= 4 else ("info" if diff > 0 else "secondary")
                _add(
                    "clima",
                    nivel,
                    "fas fa-temperature-half",
                    f"La temperatura máxima media durante el {periodo} fue de {avg_act:.1f}°C, "
                    f"frente a {avg_ant:.1f}°C en el {periodo_ant} precedente "
                    f"({abs(diff):.1f}°C {mas_menos}). "
                    + (
                        "El calor adicional puede haber condicionado la afluencia en horas centrales."
                        if diff >= 4
                        else ""
                    ),
                )
            else:
                _add(
                    "clima",
                    "secondary",
                    "fas fa-temperature-half",
                    f"La temperatura máxima media durante el {periodo} fue de {avg_act:.1f}°C, "
                    f"similar a la del {periodo_ant} precedente ({avg_ant:.1f}°C). "
                    f"Sin impacto climático térmico significativo.",
                )

        if tmaxes_act:
            n_calor = sum(1 for t in tmaxes_act if t >= 30)
            n_frio = sum(1 for t in tmaxes_act if t < 12)
            if n_calor >= 2:
                _add(
                    "clima",
                    "warning",
                    "fas fa-sun",
                    f"Se registraron {n_calor} {'días' if n_calor > 1 else 'día'} con temperatura máxima "
                    f"igual o superior a 30°C durante el {periodo}. "
                    f"Las altas temperaturas reducen el tráfico peatonal en las franjas centrales del día.",
                )
            if n_frio >= 2:
                _add(
                    "clima",
                    "info",
                    "fas fa-snowflake",
                    f"Se registraron {n_frio} {'días' if n_frio > 1 else 'día'} con temperatura máxima "
                    f"por debajo de 12°C durante el {periodo}. "
                    f"El frío intenso puede acortar la duración de las visitas y reducir el tráfico exterior.",
                )

        n_lluvia = sum(1 for v in dias_act.values() if v.get("precip", 0) > 2)
        if n_lluvia >= max(2, dias_v // 4):
            _add(
                "clima",
                "info",
                "fas fa-cloud-rain",
                f"Se registraron {n_lluvia} días con precipitaciones superiores a 2 mm durante el {periodo}. "
                f"Este factor meteorológico puede haber influido negativamente en el tráfico exterior.",
            )

    # ── EVENTOS Y FESTIVOS ────────────────────────────────────────────────────

    fmin_fest = fecha_max - timedelta(days=dias_v - 1)
    fest = [
        (f, n)
        for f, n in festivos_espana.items()
        if isinstance(f, date) and fmin_fest <= f <= fecha_max
    ]
    if fest:
        nombres = ", ".join(n for _, n in fest[:2])
        pl = "s" if len(fest) > 1 else ""
        verb = "ron" if len(fest) > 1 else ""
        _add(
            "eventos",
            "info",
            "fas fa-umbrella-beach",
            f"Durante el {periodo} se registra{verb} {len(fest)} día{pl} festivo{pl} ({nombres}). "
            f"Las jornadas festivas presentan patrones de tráfico diferenciados "
            f"respecto a los días laborables.",
        )

    if eventos:
        pasados = eventos.get("pasados_alto", [])
        proximos = eventos.get("proximos_alto", [])
        if pasados:
            if len(pasados) == 1:
                _add(
                    "eventos",
                    "primary",
                    "fas fa-star",
                    f"Durante el {periodo} se celebró un evento de alto impacto: "
                    f"«{pasados[0]['titulo']}» ({formatear_fecha(pasados[0]['fecha'])}). "
                    f"Este tipo de eventos genera picos de afluencia y puede explicar desviaciones puntuales.",
                )
            else:
                titulos = "; ".join(f"«{e['titulo']}»" for e in pasados[:3])
                mas = f" y {len(pasados)-3} más" if len(pasados) > 3 else ""
                _add(
                    "eventos",
                    "primary",
                    "fas fa-star",
                    f"Durante el {periodo} se registraron {len(pasados)} eventos de alto impacto "
                    f"({titulos}{mas}). Estos eventos pueden explicar picos y desviaciones puntuales en la afluencia.",
                )
        if proximos:
            if len(proximos) == 1:
                _add(
                    "eventos",
                    "warning",
                    "fas fa-calendar-plus",
                    f"En los próximos 28 días está previsto un evento de alto impacto: "
                    f"«{proximos[0]['titulo']}» ({formatear_fecha(proximos[0]['fecha'])}). "
                    f"Se recomienda planificar la operación del establecimiento en consecuencia.",
                )
            else:
                titulos = "; ".join(f"«{e['titulo']}»" for e in proximos[:3])
                mas = f" y {len(proximos)-3} más" if len(proximos) > 3 else ""
                _add(
                    "eventos",
                    "warning",
                    "fas fa-calendar-plus",
                    f"En los próximos 28 días están previstos {len(proximos)} eventos de alto impacto "
                    f"({titulos}{mas}). Se recomienda planificar la operación del establecimiento en consecuencia.",
                )

        # ── Cruceros ──────────────────────────────────────────────────────────
        cruceros = eventos.get("cruceros", [])
        if cruceros:
            hoy_d = fecha_max.date() if hasattr(fecha_max, "date") else fecha_max
            fmin_d = fecha_max - timedelta(days=dias_v - 1)
            fmin_d = fmin_d.date() if hasattr(fmin_d, "date") else fmin_d
            cr_periodo = [c for c in cruceros if fmin_d <= c["fecha"] <= hoy_d]
            cr_proximos = [c for c in cruceros if c["fecha"] > hoy_d]

            if cr_periodo:
                n = len(cr_periodo)
                total_pax = sum(c["n_pasajeros"] for c in cr_periodo)
                plural = "s" if n > 1 else ""
                _add(
                    "eventos",
                    "info",
                    "fas fa-ship",
                    f"Durante el {periodo} se registraron {n} escala{plural} de crucero "
                    f"con un total estimado de {total_pax:,} pasajeros en puerto. "
                    f"Los días de escala generan incrementos de tráfico turístico en el área de influencia.",
                )
            if cr_proximos:
                n = len(cr_proximos)
                total_pax = sum(c["n_pasajeros"] for c in cr_proximos)
                plural = "s" if n > 1 else ""
                _add(
                    "eventos",
                    "primary",
                    "fas fa-ship",
                    f"En los próximos 28 días están previstas {n} escala{plural} de crucero "
                    f"({total_pax:,} pasajeros estimados en puerto). "
                    f"Se esperan incrementos de tráfico turístico en el entorno de la ubicación.",
                )

    return items


# ── Section renderers ─────────────────────────────────────────────────────────

_CAT_META = {
    "trafico": ("fas fa-chart-line", "Afluencia"),
    "experiencia": ("fas fa-store", "Experiencia en tienda"),
    "integridad": ("fas fa-shield-halved", "Calidad de datos"),
    "clima": ("fas fa-cloud-sun", "Condiciones climáticas"),
    "eventos": ("fas fa-calendar-check", "Eventos"),
}


def _render_narrativa(items, extras=None):
    """
    Renderiza los insights del resumen como menú horizontal de tabs (uno por categoría).
    extras: dict {cat_key: html.Component} — contenido adicional (ej. gráficos) por tab.
    Solo aparecen tabs que tengan al menos un insight o extra content.
    """
    _LEVEL_COLOR = {
        "success": (_C_SUCCESS, "#e8f5e9"),
        "danger": (_C_DANGER, "#fdecea"),
        "warning": (_C_AMBER, "#fff8e1"),
        "primary": (_C_PRIMARY, "#e8f0fe"),
        "secondary": (_C_MUTED, "#f5f5f5"),
        "info": ("#17a2b8", "#e8f7fa"),
    }
    _CAT_ORDER = ["trafico", "experiencia", "clima", "eventos", "integridad"]

    if not items and not extras:
        return html.Div()

    from collections import OrderedDict

    groups: OrderedDict = OrderedDict()
    for item in items:
        if len(item) == 4:
            cat, level, icon_cls, texto = item
        else:
            cat, level, icon_cls, texto = "trafico", item[0], item[1], item[2]
        groups.setdefault(cat, []).append((level, icon_cls, texto))

    # Categories with only extras (no narrative items) still get a tab
    for cat in extras or {}:
        if (extras or {}).get(cat) is not None and cat not in groups:
            groups[cat] = []

    ordered_cats = sorted(
        groups.keys(),
        key=lambda c: _CAT_ORDER.index(c) if c in _CAT_ORDER else len(_CAT_ORDER),
    )

    def _make_rows(cat_items):
        rows = []
        for level, icon_cls, texto in cat_items:
            icon_color, bg = _LEVEL_COLOR.get(level, (_C_MUTED, "#f5f5f5"))
            rows.append(
                html.Div(
                    className="d-flex align-items-start gap-3 py-2",
                    style={"borderBottom": "1px solid #f0f4fb"},
                    children=[
                        html.Div(
                            html.I(
                                className=icon_cls,
                                style={"color": icon_color, "fontSize": "0.85rem"},
                            ),
                            className="d-flex align-items-center justify-content-center flex-shrink-0",
                            style={
                                "width": "30px",
                                "height": "30px",
                                "borderRadius": "8px",
                                "background": bg,
                            },
                        ),
                        html.P(
                            texto,
                            className="mb-0",
                            style={
                                "fontSize": "0.9rem",
                                "color": _C_DARK,
                                "lineHeight": "1.65",
                                "paddingTop": "3px",
                            },
                        ),
                    ],
                )
            )
        return rows

    tabs = []
    for cat in ordered_cats:
        cat_icon, cat_label = _CAT_META.get(cat, ("fas fa-circle-dot", cat.capitalize()))
        rows = _make_rows(groups[cat])
        extra = (extras or {}).get(cat)
        tab_children: list = rows[:]
        if extra:
            tab_children.append(
                html.Div(extra, className="mt-3 pt-2", style={"borderTop": "1px solid #e8eef8"})
            )

        tabs.append(
            dbc.Tab(
                html.Div(tab_children, className="pt-2"),
                label=cat_label,
                tab_id=f"narr-tab-{cat}",
                label_style={"fontSize": "0.82rem", "padding": "6px 14px"},
                active_label_style={"color": _C_PRIMARY, "fontWeight": "600"},
            )
        )

    if not tabs:
        return html.Div()

    return dbc.Card(
        dbc.CardBody(
            dbc.Tabs(tabs, active_tab=f"narr-tab-{ordered_cats[0]}"),
            className="px-3 py-2",
        ),
        className="border-0 shadow-sm rounded-4 mb-4 bg-white",
    )


def _render_zona_card(
    zona,
    r,
    a,
    d,
    dias_28,
    uid,
    periodo_label="semana",
    child_names=None,
    has_children=False,
    gap_actual=False,
    gap_anterior=False,
):
    """Tarjeta de zona: % delta en grande (hero) + visitantes absolutos + sparkline."""
    color = _color_zona(zona)
    badge_lbl, _, tooltip_role = _zona_meta(zona)
    zone_slug = _slug(zona)
    badge_id = f"pm-z-{zone_slug}-{uid}"
    spark_info_id = f"pm-spark-info-{zone_slug}-{uid}"
    gap_badge_id = f"pm-gap-{zone_slug}-{uid}"

    dv = d["visitantes"]
    if gap_actual:
        sem_color, arrow = _C_MUTED, "fas fa-wifi"
        pct_str = "—"
    elif gap_anterior:
        sem_color, arrow = _C_AMBER, "fas fa-triangle-exclamation"
        pct_str = "—"
    elif dv >= 5:
        sem_color, arrow = _C_SUCCESS, "fas fa-arrow-up"
        pct_str = f"{dv:+.0f}%"
    elif dv <= -5:
        sem_color, arrow = _C_DANGER, "fas fa-arrow-down"
        pct_str = f"{dv:+.0f}%"
    else:
        sem_color, arrow = _C_AMBER, "fas fa-minus"
        pct_str = f"{dv:+.0f}%"

    abs_str = f"{r['visitantes']:,.0f} visitantes"
    ant_str = f" · ant. {a['visitantes']:,.0f}" if a["visitantes"] else ""
    dwell_str = f" · {r['estancia']:.1f} min estancia" if r["estancia"] > 0 else ""

    sparkline = _fig_sparkline(dias_28, color)

    # Badge de alerta de calidad de datos
    if gap_actual:
        gap_ui = html.Div(
            dbc.Badge(
                [html.I(className="fas fa-wifi me-1"), "Sin datos suficientes"],
                color="warning",
                text_color="dark",
                pill=True,
                style={"fontSize": "0.62rem"},
            ),
            className="mb-2",
        )
    elif gap_anterior:
        gap_ui = html.Div(
            [
                dbc.Badge(
                    [
                        html.I(className="fas fa-triangle-exclamation me-1"),
                        "Período anterior incompleto",
                    ],
                    id=gap_badge_id,
                    color="warning",
                    text_color="dark",
                    pill=True,
                    style={"fontSize": "0.62rem", "cursor": "help"},
                ),
                dbc.Tooltip(
                    "El período de comparación incluye días sin datos registrados "
                    "(posible incidencia en el nodo). La variación puede estar sobreestimada.",
                    target=gap_badge_id,
                    placement="top",
                ),
            ],
            className="mb-2",
        )
    else:
        gap_ui = None

    return dbc.Card(
        dbc.CardBody(
            [
                # Nombre + rol
                html.Div(
                    className="d-flex align-items-center gap-2 mb-2",
                    children=[
                        html.Span(
                            zona,
                            className="fw-bold",
                            style={"fontSize": "0.80rem", "color": _C_DARK},
                        ),
                        html.Span(
                            id=badge_id,
                            children=f"· {badge_lbl}",
                            className="text-muted",
                            style={"fontSize": "0.70rem", "cursor": "help"},
                        ),
                        dbc.Tooltip(tooltip_role, target=badge_id, placement="top"),
                    ],
                ),
                # Badge de calidad de datos (solo cuando hay incidencia)
                *([gap_ui] if gap_ui else []),
                # % como métrica principal
                html.Div(
                    className="d-flex align-items-baseline gap-1 mb-1",
                    children=[
                        html.Span(
                            pct_str,
                            style={
                                "fontSize": "2.4rem",
                                "fontWeight": "800",
                                "color": sem_color,
                                "lineHeight": "1",
                            },
                        ),
                        html.I(
                            className=f"{arrow} ms-1",
                            style={"color": sem_color, "fontSize": "1rem"},
                        ),
                        html.Span(
                            f"vs {periodo_label} ant.",
                            style={"fontSize": "0.74rem", "color": _C_MUTED, "marginLeft": "6px"},
                        ),
                    ],
                ),
                # Visitantes absolutos como subtítulo
                html.P(
                    abs_str + ant_str + dwell_str,
                    className="text-muted mb-2",
                    style={"fontSize": "0.70rem", "lineHeight": "1.4"},
                ),
                # Sparkline 28d
                (
                    html.Div(
                        [
                            html.Div(
                                className="d-flex justify-content-between align-items-center mb-1",
                                children=[
                                    html.Span(
                                        "Tendencia 28d",
                                        style={
                                            "fontSize": "0.62rem",
                                            "color": _C_MUTED,
                                            "textTransform": "uppercase",
                                            "letterSpacing": "0.4px",
                                        },
                                    ),
                                    html.I(
                                        className="fas fa-circle-info",
                                        id=spark_info_id,
                                        style={
                                            "color": _C_MUTED,
                                            "fontSize": "0.65rem",
                                            "cursor": "help",
                                        },
                                    ),
                                    dbc.Tooltip(
                                        "Visitantes diarios · últimos 28 días. "
                                        "Línea continua = tráfico real; línea punteada = tendencia "
                                        "(verde = subiendo, roja = bajando).",
                                        target=spark_info_id,
                                        placement="top",
                                    ),
                                ],
                            ),
                            (
                                dcc.Graph(
                                    id=f"spark-{zone_slug}-{uid}",
                                    figure=sparkline,
                                    config=_CFG_GRAPH,
                                    style={"height": "68px"},
                                )
                                if sparkline
                                else html.P(
                                    "Sin datos de tendencia",
                                    className="text-muted small text-center mb-0 py-2",
                                )
                            ),
                        ]
                    )
                    if sparkline
                    else html.P(
                        "Sin datos de tendencia",
                        className="text-muted small text-center mb-0 py-2",
                    )
                ),
                # Child zone chips — shown only on parent zone cards
                *(
                    [
                        html.Div(
                            [
                                html.Span(
                                    [html.I(className="fas fa-sitemap me-1"), "Subzonas: "],
                                    style={"fontSize": "0.63rem", "color": _C_MUTED},
                                ),
                                *[
                                    dbc.Badge(
                                        cn,
                                        color="light",
                                        text_color="secondary",
                                        className="me-1 border",
                                        style={"fontSize": "0.59rem"},
                                    )
                                    for cn in child_names
                                ],
                            ],
                            className="mt-2 pt-2 border-top",
                        )
                    ]
                    if child_names
                    else []
                ),
            ],
            className="p-3",
        ),
        className="border-0 shadow-sm rounded-4 h-100",
        style={
            "borderTop": f"3px solid {color}",
            "overflow": "visible",
            **({"background": "rgba(0,82,204,0.04)"} if has_children else {}),
        },
    )


def _parse_hourly_pm(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        parsed = json.loads(str(val))
        if isinstance(parsed, list) and len(parsed) == 24:
            return [float(v) for v in parsed]
    except Exception:
        pass
    return None


def _fig_hora_pico(df_todas_zonas, fecha_max=None, dias=7):
    """Distribución horaria — período actual (barras) vs anterior (línea translúcida)."""
    if "hourly_visits" not in df_todas_zonas.columns:
        return None

    def _acum_horario(df_sub):
        acum = [0.0] * 24
        n = 0
        for val in df_sub["hourly_visits"]:
            parsed = _parse_hourly_pm(val)
            if parsed:
                for h, v in enumerate(parsed):
                    acum[h] += v
                n += 1
        if n == 0 or sum(acum) == 0:
            return None
        return [v / n for v in acum]

    if fecha_max is not None and "fecha_dt" in df_todas_zonas.columns:
        fmin_act = fecha_max - timedelta(days=dias - 1)
        fmin_ant = fmin_act - timedelta(days=dias)
        fmax_ant = fmin_act - timedelta(days=1)
        df_act = df_todas_zonas[
            (df_todas_zonas["fecha_dt"] >= fmin_act) & (df_todas_zonas["fecha_dt"] <= fecha_max)
        ]
        df_ant = df_todas_zonas[
            (df_todas_zonas["fecha_dt"] >= fmin_ant) & (df_todas_zonas["fecha_dt"] <= fmax_ant)
        ]
    else:
        df_act = df_todas_zonas
        df_ant = pd.DataFrame(columns=df_todas_zonas.columns)

    avg_act = _acum_horario(df_act)
    avg_ant = _acum_horario(df_ant) if not df_ant.empty else None

    if avg_act is None:
        return None

    horas = [f"{h:02d}h" for h in range(24)]
    max_v = max(max(avg_act), max(avg_ant) if avg_ant else 0) or 1
    peak_h = int(np.argmax(avg_act))
    colors = [f"rgba(0,82,204,{0.18 + 0.72 * v / max_v:.2f})" for v in avg_act]
    texts = [f"<b>{int(v)}</b>" if i == peak_h else "" for i, v in enumerate(avg_act)]

    fig = go.Figure()
    if avg_ant and sum(avg_ant) > 0:
        fig.add_trace(
            go.Scatter(
                x=horas,
                y=avg_ant,
                mode="lines",
                line=dict(color="rgba(0,82,204,0.28)", width=1.5, dash="dot"),
                fill="tozeroy",
                fillcolor="rgba(0,82,204,0.04)",
                hovertemplate="Anterior · %{x}: <b>%{y:.0f}</b><extra></extra>",
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Bar(
            x=horas,
            y=avg_act,
            marker=dict(color=colors, line=dict(width=0), cornerradius=5),
            text=texts,
            textposition="outside",
            textfont=dict(size=10, color=_C_DARK),
            hovertemplate="Actual · %{x}: <b>%{y:.0f}</b> visitas/hora<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=180,
        margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(
            showgrid=False, tickfont=dict(size=9, color=_C_DARK), fixedrange=True, tickangle=0
        ),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.35]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.12,
        barmode="overlay",
    )
    return fig


def _fig_nuevos_ratio(df_todas_zonas, fecha_max, dias=7):
    """% de visitantes nuevos — período actual con referencia del período anterior."""
    if (
        "new_visitors" not in df_todas_zonas.columns
        or "unique_visitors" not in df_todas_zonas.columns
    ):
        return None

    fmin_act = fecha_max - timedelta(days=dias - 1)
    fmin_ant = fmin_act - timedelta(days=dias)
    fmax_ant = fmin_act - timedelta(days=1)

    def _ratio_diario(fmin, fmax):
        df = df_todas_zonas[
            (df_todas_zonas["fecha_dt"] >= fmin) & (df_todas_zonas["fecha_dt"] <= fmax)
        ].copy()
        if df.empty:
            return pd.DataFrame()
        por_dia = (
            df.groupby("fecha_dt")
            .agg(
                nuevos=("new_visitors", "sum"),
                total=("unique_visitors", "sum"),
            )
            .reset_index()
        )
        por_dia = por_dia[por_dia["total"] > 0]
        if por_dia.empty:
            return pd.DataFrame()
        por_dia["pct"] = (por_dia["nuevos"] / por_dia["total"] * 100).clip(0, 100)
        return por_dia

    pd_act = _ratio_diario(fmin_act, fecha_max)
    pd_ant = _ratio_diario(fmin_ant, fmax_ant)

    if pd_act.empty:
        return None

    media_act = pd_act["pct"].mean()
    fig = go.Figure()
    if not pd_ant.empty:
        media_ant = pd_ant["pct"].mean()
        fig.add_hline(
            y=media_ant,
            line_dash="dot",
            line_color="rgba(0,82,204,0.30)",
            annotation_text=f"Ant. {media_ant:.0f}%",
            annotation_position="bottom right",
            annotation_font=dict(size=10, color="rgba(0,82,204,0.55)"),
        )
    fig.add_trace(
        go.Scatter(
            x=pd_act["fecha_dt"],
            y=pd_act["pct"],
            mode="lines+markers",
            fill="tozeroy",
            fillcolor="rgba(0,82,204,0.07)",
            line=dict(color=_C_PRIMARY, width=2),
            marker=dict(size=5),
            hovertemplate="%{x}: <b>%{y:.0f}%</b> nuevos<extra></extra>",
        )
    )
    fig.add_hline(
        y=media_act,
        line_dash="dot",
        line_color=_C_MUTED,
        annotation_text=f"Media {media_act:.0f}%",
        annotation_position="top right",
        annotation_font=dict(size=10, color=_C_MUTED),
    )
    fig.update_layout(
        height=180,
        margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, 120]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _fig_semanas_mes(df, fecha_max):
    """Visitantes por semana — 4 semanas actuales (sólido) vs 4 anteriores (translúcido)."""
    if df.empty or "unique_visitors" not in df.columns:
        return None

    fmin_act = fecha_max - timedelta(days=27)
    fmin_ant = fmin_act - timedelta(days=28)
    fmax_ant = fmin_act - timedelta(days=1)

    def _por_semana(fmin, fmax):
        df_s = df[(df["fecha_dt"] >= fmin) & (df["fecha_dt"] <= fmax)].copy()
        if df_s.empty:
            return pd.Series([], dtype=float), []
        df_s["fecha_ts"] = pd.to_datetime(df_s["fecha_dt"])
        df_s["sem"] = df_s["fecha_ts"].dt.to_period("W")
        por_sem = df_s.groupby("sem")["unique_visitors"].sum().sort_index()
        hover = [
            f"{p.start_time.strftime('%d/%m')}–{p.end_time.strftime('%d/%m')}"
            for p in por_sem.index
        ]
        return por_sem, hover

    sem_act, hover_act = _por_semana(fmin_act, fecha_max)
    sem_ant, hover_ant = _por_semana(fmin_ant, fmax_ant)

    if sem_act.empty or len(sem_act) < 2:
        return None

    n = len(sem_act)
    labels = [f"Sem {i + 1}" for i in range(n)]
    vals_act = sem_act.values.tolist()
    vals_ant = sem_ant.values.tolist() if len(sem_ant) == n else [0] * n
    hover_ant2 = hover_ant if len(hover_ant) == n else labels

    opacities = [0.28 + 0.72 * (i / max(n - 1, 1)) for i in range(n)]
    colors_act = [f"rgba(0,82,204,{op:.2f})" for op in opacities]
    max_v = max(max(vals_act) if vals_act else 0, max(vals_ant) if vals_ant else 0) or 1

    fig = go.Figure()
    if any(v > 0 for v in vals_ant):
        fig.add_trace(
            go.Bar(
                x=labels,
                y=vals_ant,
                marker=dict(
                    color="rgba(0,82,204,0.14)",
                    line=dict(color="rgba(0,82,204,0.35)", width=1),
                    cornerradius=5,
                ),
                customdata=hover_ant2,
                hovertemplate="Anterior · %{x} (%{customdata}): <b>%{y:,.0f}</b><extra></extra>",
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=vals_act,
            marker=dict(color=colors_act, line=dict(width=0), cornerradius=5),
            text=[f"<b>{int(v):,}</b>" for v in vals_act],
            textposition="outside",
            textfont=dict(size=11, color=_C_DARK),
            customdata=hover_act,
            hovertemplate="Actual · %{x} (%{customdata}): <b>%{y:,.0f}</b><extra></extra>",
            cliponaxis=False,
            showlegend=False,
        )
    )
    fig.update_layout(
        barmode="group",
        height=180,
        margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.33]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.25,
        bargroupgap=0.06,
    )
    return fig


def _fig_temperatura_trafico(df, clima: dict, fecha_max, dias: int = 7):
    """Visitantes (barras, eje izq.) + temperatura máx (línea, eje der.). Actual vs anterior."""
    if not clima:
        return None
    fmin_act = fecha_max - timedelta(days=dias - 1)
    fmin_ant = fmin_act - timedelta(days=dias)
    fmax_ant = fmin_act - timedelta(days=1)
    _dias_es = {0: "L", 1: "M", 2: "X", 3: "J", 4: "V", 5: "S", 6: "D"}

    def _serie(fmin, fmax):
        rows, cur = [], fmin
        while cur <= fmax:
            ds = cur.strftime("%Y-%m-%d")
            vis = (
                int(df[df["fecha_dt"] == cur]["unique_visitors"].sum())
                if "unique_visitors" in df.columns
                else 0
            )
            cl = clima.get(ds, {})
            lbl = _dias_es[cur.weekday()] if dias <= 7 else cur.strftime("%d/%m")
            rows.append({"lbl": lbl, "vis": vis, "tmax": cl.get("tmax"), "fecha": ds})
            cur += timedelta(days=1)
        return rows

    act = _serie(fmin_act, fecha_max)
    ant = _serie(fmin_ant, fmax_ant)
    if not any(d["tmax"] is not None for d in act + ant):
        return None

    x_act = [d["lbl"] for d in act]
    x_ant = [d["lbl"] for d in ant]
    max_vis = max((d["vis"] for d in act + ant), default=1) or 1

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_ant,
            y=[d["vis"] for d in ant],
            name="Visitas ant.",
            marker=dict(
                color="rgba(0,82,204,0.16)",
                line=dict(color="rgba(0,82,204,0.32)", width=1),
                cornerradius=5,
            ),
            yaxis="y",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Bar(
            x=x_act,
            y=[d["vis"] for d in act],
            name="Visitas act.",
            marker=dict(color="rgba(0,82,204,0.78)", cornerradius=5),
            yaxis="y",
            showlegend=False,
        )
    )
    tmax_act = [d["tmax"] for d in act]
    tmax_ant = [d["tmax"] for d in ant]
    if any(t is not None for t in tmax_ant):
        fig.add_trace(
            go.Scatter(
                x=x_ant,
                y=tmax_ant,
                name="°C ant.",
                line=dict(color="rgba(230,126,34,0.40)", width=1.5, dash="dot"),
                mode="lines",
                yaxis="y2",
                showlegend=False,
            )
        )
    if any(t is not None for t in tmax_act):
        fig.add_trace(
            go.Scatter(
                x=x_act,
                y=tmax_act,
                name="°C act.",
                line=dict(color="#e67e22", width=2),
                mode="lines+markers",
                marker=dict(size=5),
                yaxis="y2",
                showlegend=False,
            )
        )
    fig.update_layout(
        barmode="group",
        bargap=0.22,
        bargroupgap=0.06,
        yaxis=dict(visible=False, range=[0, max_vis * 1.35], fixedrange=True),
        yaxis2=dict(
            title="°C",
            overlaying="y",
            side="right",
            showgrid=False,
            tickfont=dict(size=9, color="#e67e22"),
            fixedrange=True,
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=12, b=8, l=8, r=38),
        font=dict(size=10, family="system-ui"),
        xaxis=dict(showgrid=False, tickfont=dict(size=11, color=_C_DARK), fixedrange=True),
    )
    return fig


def _fig_lluvia_trafico(df, clima: dict, fecha_max, dias: int = 7):
    """Visitantes (barras sólidas/translúcidas) + precipitación (área, eje der.). Actual vs anterior."""
    if not clima:
        return None
    fmin_act = fecha_max - timedelta(days=dias - 1)
    fmin_ant = fmin_act - timedelta(days=dias)
    fmax_ant = fmin_act - timedelta(days=1)
    _dias_es = {0: "L", 1: "M", 2: "X", 3: "J", 4: "V", 5: "S", 6: "D"}

    def _serie(fmin, fmax):
        rows, cur = [], fmin
        while cur <= fmax:
            ds = cur.strftime("%Y-%m-%d")
            vis = (
                int(df[df["fecha_dt"] == cur]["unique_visitors"].sum())
                if "unique_visitors" in df.columns
                else 0
            )
            cl = clima.get(ds, {})
            lbl = _dias_es[cur.weekday()] if dias <= 7 else cur.strftime("%d/%m")
            rows.append({"lbl": lbl, "vis": vis, "precip": cl.get("precip") or 0})
            cur += timedelta(days=1)
        return rows

    act = _serie(fmin_act, fecha_max)
    ant = _serie(fmin_ant, fmax_ant)
    if not any(d["precip"] > 0 for d in act + ant):
        return None

    x_act = [d["lbl"] for d in act]
    x_ant = [d["lbl"] for d in ant]
    max_vis = max((d["vis"] for d in act + ant), default=1) or 1

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_ant,
            y=[d["vis"] for d in ant],
            name="Visitas ant.",
            marker=dict(
                color="rgba(0,82,204,0.16)",
                line=dict(color="rgba(0,82,204,0.32)", width=1),
                cornerradius=5,
            ),
            yaxis="y",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Bar(
            x=x_act,
            y=[d["vis"] for d in act],
            name="Visitas act.",
            marker=dict(color="rgba(0,82,204,0.78)", cornerradius=5),
            yaxis="y",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_ant,
            y=[d["precip"] for d in ant],
            name="Lluvia ant.",
            fill="tozeroy",
            fillcolor="rgba(41,128,185,0.10)",
            line=dict(color="rgba(41,128,185,0.30)", width=1, dash="dot"),
            mode="lines",
            yaxis="y2",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_act,
            y=[d["precip"] for d in act],
            name="Lluvia act.",
            fill="tozeroy",
            fillcolor="rgba(41,128,185,0.22)",
            line=dict(color="rgba(41,128,185,0.70)", width=1.5),
            mode="lines+markers",
            marker=dict(size=5, symbol="circle"),
            yaxis="y2",
            showlegend=False,
        )
    )
    fig.update_layout(
        barmode="group",
        bargap=0.22,
        bargroupgap=0.06,
        yaxis=dict(visible=False, range=[0, max_vis * 1.35], fixedrange=True),
        yaxis2=dict(
            title="mm",
            overlaying="y",
            side="right",
            showgrid=False,
            tickfont=dict(size=9, color="rgba(41,128,185,0.9)"),
            fixedrange=True,
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=12, b=8, l=8, r=38),
        font=dict(size=10, family="system-ui"),
        xaxis=dict(showgrid=False, tickfont=dict(size=11, color=_C_DARK), fixedrange=True),
    )
    return fig


def _render_pm_questions(
    df, zonas_data, fecha_max, uid, ventana="semana", child_zones=None, clima=None
):
    """
    Responde gráficamente las preguntas habituales de un PM sobre el tráfico.
    Cada carta tiene una pregunta en lenguaje natural + gráfico directo.
    Los gráficos segmentados por zona usan solo zonas padre.
    """

    def _q_card(pregunta, subtitulo, fig, gid, height):
        if fig is None:
            return None
        return dbc.Card(
            dbc.CardBody(
                [
                    html.P(
                        pregunta,
                        className="fw-bold mb-0",
                        style={"fontSize": "0.96rem", "color": _C_DARK},
                    ),
                    html.P(
                        subtitulo,
                        className="text-muted mb-2",
                        style={"fontSize": "0.78rem", "lineHeight": "1.4"},
                    ),
                    dcc.Graph(
                        id=gid,
                        figure=fig,
                        config=_CFG_GRAPH,
                        style={"height": height},
                    ),
                ],
                className="px-4 py-3",
            ),
            className="border-0 shadow-sm rounded-4 h-100 bg-white",
        )

    _cz = child_zones or set()
    zonas_top = [z for z in zonas_data if z["zona"] not in _cz] or zonas_data
    df_top = df[~df["Zona"].isin(_cz)].copy() if _cz else df

    dias_v = 28 if ventana == "mes" else 7
    _periodo = "último mes (28 días)" if ventana == "mes" else "última semana (7 días)"
    _periodo_corto = "último mes" if ventana == "mes" else "última semana"
    _lbl_dias = (
        "Media por día · último mes" if ventana == "mes" else "Visitantes por día · esta semana"
    )

    preguntas = []

    _ant_lbl = "28 días anteriores" if ventana == "mes" else "7 días anteriores"

    # Gráfico semana-a-semana: solo en modo mes
    if ventana == "mes":
        preguntas.append(
            (
                _fig_semanas_mes(df, fecha_max),
                f"q-semanas-{uid}",
                "¿Cómo evolucionó el tráfico semana a semana?",
                f"Visitantes por semana · sólido = {_periodo_corto} · translúcido = {_ant_lbl}",
                "180px",
            )
        )

    preguntas += [
        (
            _fig_dias_semana(df, fecha_max, dias=dias_v),
            f"q-dias-{uid}",
            "¿Cuándo llegan los visitantes?",
            "Media por día · tono más oscuro = día pico · sólido = actual · translúcido = anterior",
            "165px",
        ),
        (
            _fig_hora_pico(df_top, fecha_max=fecha_max, dias=dias_v),
            f"q-hora-{uid}",
            "¿A qué hora llegan?",
            "Distribución horaria · barras = actual · línea punteada = anterior",
            "180px",
        ),
        (
            _fig_finde_vs_laborable(df, fecha_max, dias=dias_v),
            f"q-finde-{uid}",
            "¿Rinde mejor el fin de semana o entre semana?",
            f"Visitantes/día (media) · sólido = actual · translúcido = {_ant_lbl}",
            "180px",
        ),
        (
            _fig_nuevos_ratio(df_top, fecha_max, dias=dias_v),
            f"q-nuevos-{uid}",
            "¿Cuántos visitantes son nuevos?",
            "% visitantes nuevos · línea azul = media actual · línea punteada tenue = media anterior",
            "180px",
        ),
        (
            _fig_dwell_zonas(zonas_top, child_zones=_cz),
            f"q-dwell-{uid}",
            "¿Cuánto tiempo se quedan?",
            f"Tiempo medio de permanencia por zona principal · {_periodo_corto}",
            "180px",
        ),
        (
            _fig_embudo_conversion(zonas_top),
            f"q-embudo-{uid}",
            "¿Cuántos visitantes convierten?",
            f"Visitantes por etapa · {_periodo_corto} · % respecto al paso anterior",
            "180px",
        ),
    ]

    # ── Gráficos de clima (si hay datos disponibles) ───────────────────────
    if clima:
        _ant_lbl_c = "28 días anteriores" if ventana == "mes" else "7 días anteriores"
        fig_temp = _fig_temperatura_trafico(df, clima, fecha_max, dias=dias_v)
        if fig_temp:
            preguntas.append(
                (
                    fig_temp,
                    f"q-temp-{uid}",
                    "¿Cómo afectó la temperatura al tráfico?",
                    f"Barras = visitas (sólido = actual · translúcido = {_ant_lbl_c}) · línea naranja = temperatura máx.",
                    "190px",
                )
            )
        fig_lluvia = _fig_lluvia_trafico(df, clima, fecha_max, dias=dias_v)
        if fig_lluvia:
            preguntas.append(
                (
                    fig_lluvia,
                    f"q-lluvia-{uid}",
                    "¿Hubo precipitaciones que condicionaron el tráfico?",
                    f"Barras = visitas (sólido = actual · translúcido = {_ant_lbl_c}) · área azul = mm de lluvia",
                    "190px",
                )
            )

    cols = []
    for fig, gid, preg, sub, h in preguntas:
        card = _q_card(preg, sub, fig, gid, h)
        if card:
            cols.append(dbc.Col(card, xs=12, md=6, className="mb-3"))

    if not cols:
        return html.Div()

    _v_lbl = "últimos 28 días" if ventana == "mes" else "últimos 7 días"

    _leyenda_comparativa = html.Div(
        [
            html.Div(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "10px",
                            "height": "10px",
                            "background": "rgba(0,82,204,0.85)",
                            "borderRadius": "2px",
                            "marginRight": "5px",
                            "flexShrink": "0",
                        }
                    ),
                    html.Span("Período actual", style={"fontSize": "0.71rem", "color": _C_DARK}),
                ],
                className="d-flex align-items-center me-4",
            ),
            html.Div(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "10px",
                            "height": "10px",
                            "background": "rgba(0,82,204,0.14)",
                            "border": "1px solid rgba(0,82,204,0.35)",
                            "borderRadius": "2px",
                            "marginRight": "5px",
                            "flexShrink": "0",
                        }
                    ),
                    html.Span(
                        "Período anterior equivalente",
                        style={"fontSize": "0.71rem", "color": _C_MUTED},
                    ),
                ],
                className="d-flex align-items-center",
            ),
        ],
        className="d-flex align-items-center mb-3 ps-1",
    )

    return html.Div(
        [
            html.H5(
                [
                    html.I(className="fas fa-magnifying-glass me-2 text-primary"),
                    "Patrones de comportamiento",
                ],
                className="fw-bold mb-1",
                style={"fontSize": "1.15rem", "color": _C_DARK},
            ),
            html.P(
                f"Distribución del tráfico comparada con el período equivalente anterior · {_v_lbl}.",
                className="text-muted mb-2",
                style={"fontSize": "0.84rem"},
            ),
            _leyenda_comparativa,
            dbc.Row(cols, className="g-3"),
        ],
        className="mb-4",
    )


# ── Eventos externos ─────────────────────────────────────────────────────────

_UNIVERSAL_KEYS = frozenset(
    {
        "ev_festivo_regional",
        "ev_vacaciones_escolares",
        "ev_rank_concierto",
        "ev_rank_deportivo",
        "ev_rank_festival",
        "ev_rank_municipal",
        "ev_rank_total",
        "llueve",
        "temp_max",
        "temp_min",
    }
)

_FEATURE_META = {
    "n_pasajeros_crucero_dia": ("Pasajeros de crucero", "pax totales", "sum", "#1abc9c"),
    "n_turistas_isocrona": ("Turistas zona 0-15 min", "pers. estimadas", "sum", "#3498db"),
    "n_eventos_gran_via": ("Eventos Gran Vía", "eventos en rango", "sum", "#9b59b6"),
    "afluencia_metro_gran_via": ("Metro Gran Vía", "viajeros validados", "sum", "#e67e22"),
    "afluencia_metro_callao": ("Metro Callao", "viajeros validados", "sum", "#00539B"),
    "ev_vacaciones_escolares": ("Vacaciones escolares", "días en el mes", "sum", "#8e44ad"),
    "cal_escolar_is_break": ("Período vacacional", "días en el mes", "sum", "#8e44ad"),
    "cal_escolar_dias_hasta": ("Días hasta próx. vacaciones", "días (media)", "mean", "#8e44ad"),
}
_DEFAULT_COLOR = "#0052CC"


def _render_eventos_externos(location_uuid: str, fecha_max) -> html.Div | None:
    """
    Sección 'Contexto externo': agrega por semana y mes las features de
    store_features_ext exclusivas de la ubicación (excluye features universales).
    Devuelve None si no hay datos.
    """
    try:
        from src.db.store import get_conn

        conn = get_conn()

        desde = fecha_max - timedelta(days=119)  # ~4 meses para cubrir 4 semanas + 3 meses
        rows = conn.execute(
            """SELECT feature_key, fecha::text, value
               FROM   store_features_ext
               WHERE  location_uuid = ?
                 AND  value IS NOT NULL
                 AND  fecha >= ?
               ORDER  BY feature_key, fecha""",
            [location_uuid, str(desde.date() if hasattr(desde, "date") else desde)],
        ).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    df_ext = pd.DataFrame(rows, columns=["feature_key", "fecha", "value"])
    df_ext["fecha"] = pd.to_datetime(df_ext["fecha"])

    keys_loc = [k for k in df_ext["feature_key"].unique() if k not in _UNIVERSAL_KEYS]
    if not keys_loc:
        return None

    df_ext = df_ext[df_ext["feature_key"].isin(keys_loc)].copy()
    df_ext["semana_iso"] = df_ext["fecha"].dt.to_period("W").dt.start_time
    df_ext["mes"] = df_ext["fecha"].dt.to_period("M").dt.to_timestamp()

    _MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    feature_cards = []
    for fk in sorted(keys_loc):
        meta = _FEATURE_META.get(fk, (fk.replace("_", " ").title(), "", "sum", _DEFAULT_COLOR))
        label, unidad, agg_fn, color = meta

        df_k = df_ext[df_ext["feature_key"] == fk]

        # ── Semanas (últimas 4 completas) ──────────────────────────────
        sem_agg = (
            df_k.groupby("semana_iso")["value"]
            .agg(agg_fn)
            .reset_index()
            .sort_values("semana_iso")
            .tail(5)
        )
        sem_labels = [f"S{r.isocalendar()[1]}" for r in sem_agg["semana_iso"].dt.date]
        sem_vals = sem_agg["value"].tolist()

        # ── Meses (últimos 3) ──────────────────────────────────────────
        mes_agg = df_k.groupby("mes")["value"].agg(agg_fn).reset_index().sort_values("mes").tail(4)
        mes_labels = [f"{_MESES_ES[r.month - 1]} {r.year}" for r in mes_agg["mes"].dt.date]
        mes_vals = mes_agg["value"].tolist()

        def _bar_fig(x_vals, y_vals, title):
            fig = go.Figure(
                go.Bar(
                    x=x_vals,
                    y=y_vals,
                    marker=dict(color=color, opacity=0.85, cornerradius=5),
                    text=[f"<b>{int(v):,}</b>" if v >= 1 else f"<b>{v:.1f}</b>" for v in y_vals],
                    textposition="outside",
                    textfont=dict(size=10, color="#2c3e50"),
                )
            )
            fig.update_layout(
                title=dict(text=title, font=dict(size=11, color="#7f8c8d"), x=0),
                plot_bgcolor="white",
                paper_bgcolor="white",
                margin=dict(t=30, b=10, l=10, r=10),
                xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                yaxis=dict(showgrid=True, gridcolor="#f0f0f0", visible=False),
                height=150,
            )
            return fig

        gid_sem = f"ext-{location_uuid[:8]}-{fk}-sem"
        gid_mes = f"ext-{location_uuid[:8]}-{fk}-mes"

        fig_sem = _bar_fig(sem_labels, sem_vals, "Por semana") if sem_vals else None
        fig_mes = _bar_fig(mes_labels, mes_vals, "Por mes") if mes_vals else None

        # KPI rápido: última semana vs anterior
        delta_badge = html.Span()
        if len(sem_vals) >= 2 and sem_vals[-2] > 0:
            pct = (sem_vals[-1] - sem_vals[-2]) / sem_vals[-2] * 100
            color_b = "#27ae60" if pct > 0 else "#e74c3c"
            flecha = "▲" if pct > 0 else "▼"
            delta_badge = html.Span(
                f"{flecha} {pct:+.1f}% vs semana ant.",
                style={"color": color_b, "fontSize": "0.75rem", "fontWeight": "600"},
            )

        val_ult = (
            f"{int(sem_vals[-1]):,}"
            if sem_vals and sem_vals[-1] >= 1
            else (f"{sem_vals[-1]:.2f}" if sem_vals else "—")
        )
        unidad_txt = f" {unidad}" if unidad else ""

        header_row = html.Div(
            [
                html.I(className="fas fa-satellite-dish me-2", style={"color": color}),
                html.Span(
                    label,
                    className="fw-bold me-2",
                    style={"fontSize": "0.9rem", "color": "#2c3e50"},
                ),
                html.Span(
                    [val_ult, unidad_txt, " esta semana"],
                    className="text-muted me-2",
                    style={"fontSize": "0.78rem"},
                ),
                delta_badge,
            ],
            className="d-flex align-items-center flex-wrap gap-1 mb-2",
        )

        graficos = dbc.Row(
            [
                dbc.Col(
                    (
                        dcc.Graph(
                            id=gid_sem,
                            figure=fig_sem,
                            config={"displayModeBar": False},
                            style={"height": "150px"},
                        )
                        if fig_sem
                        else html.Div()
                    ),
                    xs=12,
                    md=6,
                ),
                dbc.Col(
                    (
                        dcc.Graph(
                            id=gid_mes,
                            figure=fig_mes,
                            config={"displayModeBar": False},
                            style={"height": "150px"},
                        )
                        if fig_mes
                        else html.Div()
                    ),
                    xs=12,
                    md=6,
                ),
            ],
            className="g-2",
        )

        feature_cards.append(html.Div([header_row, graficos], className="mb-3"))

    if not feature_cards:
        return None

    return html.Div(
        [
            html.Div(
                [
                    html.I(className="fas fa-broadcast-tower me-2 text-primary"),
                    html.Span(
                        "Contexto externo",
                        className="fw-bold text-dark",
                        style={"fontSize": "1rem"},
                    ),
                ],
                className="d-flex align-items-center border-bottom pb-2 mb-3",
            ),
            html.Div(feature_cards),
        ],
        className="mb-4 p-3 bg-white rounded-4 shadow-sm border",
    )


def _render_eventos_signals(
    location_uuid: str, fecha_max, ventana: str = "semana"
) -> html.Div | None:
    """
    Tab 'Eventos' — señales externas: KPI % delta del período + cobertura anual (12 meses).
    Meses sin datos marcados con 'Sin datos'. Sin duplicar los gráficos del acordeón.
    """
    try:
        from src.db.store import get_conn

        conn = get_conn()
        anio_actual = fecha_max.year if hasattr(fecha_max, "year") else pd.Timestamp(fecha_max).year
        desde = (
            fecha_max.replace(year=anio_actual - 1, month=1, day=1)
            if hasattr(fecha_max, "replace")
            else pd.Timestamp(fecha_max).replace(year=anio_actual - 1, month=1, day=1)
        )
        rows = conn.execute(
            """SELECT feature_key, fecha::text, value
               FROM store_features_ext
               WHERE location_uuid = ? AND value IS NOT NULL AND fecha >= ?
               ORDER BY feature_key, fecha""",
            [location_uuid, str(desde.date() if hasattr(desde, "date") else desde)],
        ).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    df_ext = pd.DataFrame(rows, columns=["feature_key", "fecha", "value"])
    df_ext["fecha"] = pd.to_datetime(df_ext["fecha"])

    keys_loc = [k for k in df_ext["feature_key"].unique() if k not in _UNIVERSAL_KEYS]
    if not keys_loc:
        return None

    df_ext = df_ext[df_ext["feature_key"].isin(keys_loc)].copy()

    dias_v = 28 if ventana == "mes" else 7
    fmax = pd.Timestamp(fecha_max)
    fmin_act = fmax - timedelta(days=dias_v - 1)
    fmin_ant = fmin_act - timedelta(days=dias_v)
    per_lbl = "mes" if ventana == "mes" else "semana"

    _MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    cards = []
    for fk in sorted(keys_loc):
        meta = _FEATURE_META.get(fk, (fk.replace("_", " ").title(), "", "sum", _DEFAULT_COLOR))
        label, unidad, agg_fn, color = meta
        df_k = df_ext[df_ext["feature_key"] == fk]

        # ── KPI: % delta período actual vs anterior ────────────────────
        def _agg(series):
            return series.sum() if agg_fn == "sum" else series.mean()

        v_act = _agg(df_k.loc[(df_k["fecha"] >= fmin_act) & (df_k["fecha"] <= fmax), "value"])
        v_ant = _agg(df_k.loc[(df_k["fecha"] >= fmin_ant) & (df_k["fecha"] < fmin_act), "value"])

        pct = (v_act - v_ant) / v_ant * 100 if v_ant > 0 else None
        val_txt = f"{int(v_act):,}" if v_act >= 1 else f"{v_act:.1f}"
        unidad_txt = f" {unidad}" if unidad else ""

        if pct is not None:
            if abs(pct) < 0.5:
                kpi_el = html.Span(
                    f"= {pct:+.1f}% vs {per_lbl} ant.",
                    style={"color": _C_MUTED, "fontSize": "0.78rem", "fontWeight": "600"},
                )
            else:
                flecha = "▲" if pct > 0 else "▼"
                kpi_color = "#27ae60" if pct > 0 else "#e74c3c"
                kpi_el = html.Span(
                    f"{flecha} {pct:+.1f}% vs {per_lbl} ant.",
                    style={"color": kpi_color, "fontSize": "0.78rem", "fontWeight": "600"},
                )
        else:
            kpi_el = html.Span(
                "Sin comparativa", className="text-muted", style={"fontSize": "0.78rem"}
            )

        header_row = html.Div(
            [
                html.I(className=f"{_icon_for_feature(fk)} me-2", style={"color": color}),
                html.Span(
                    label,
                    className="fw-semibold me-2",
                    style={"fontSize": "0.9rem", "color": _C_DARK},
                ),
                html.Span(
                    f"{val_txt}{unidad_txt} este {per_lbl}",
                    className="text-muted me-2",
                    style={"fontSize": "0.78rem"},
                ),
                kpi_el,
            ],
            className="d-flex align-items-center flex-wrap gap-1 mb-2",
        )

        # ── Cobertura anual: 12 meses, marcando ausencia ───────────────
        df_anio = df_k[df_k["fecha"].dt.year == anio_actual].copy()
        df_anio["mes_num"] = df_anio["fecha"].dt.month
        mes_agg = df_anio.groupby("mes_num")["value"].agg(agg_fn)

        y_vals, bar_colors, bar_text, text_pos, text_colors = [], [], [], [], []
        for m in range(1, 13):
            if m in mes_agg.index and mes_agg[m] > 0:
                v = float(mes_agg[m])
                y_vals.append(v)
                bar_colors.append(_hex_rgba(color, 0.88))
                bar_text.append(f"<b>{int(v):,}</b>" if v >= 1 else f"<b>{v:.1f}</b>")
                text_pos.append("outside")
                text_colors.append(_C_DARK)
            else:
                y_vals.append(0.0)
                bar_colors.append("rgba(224,224,224,0.55)")
                bar_text.append("Sin datos")
                text_pos.append("inside")
                text_colors.append("#aaaaaa")

        max_v = max((v for v in y_vals if v > 0), default=1)
        y_display = [v if v > 0 else max_v * 0.06 for v in y_vals]

        fig = go.Figure(
            go.Bar(
                x=_MESES_ES,
                y=y_display,
                text=bar_text,
                textposition=text_pos,
                textfont=dict(size=9, color=text_colors),
                marker_color=bar_colors,
                hovertemplate=[
                    (
                        f"{_MESES_ES[i]}: <b>{int(y_vals[i]):,}</b><extra></extra>"
                        if bar_colors[i] != "#e8e8e8"
                        else f"{_MESES_ES[i]}: sin datos<extra></extra>"
                    )
                    for i in range(12)
                ],
            )
        )
        fig.update_layout(
            height=155,
            margin=dict(t=10, b=4, l=4, r=4),
            plot_bgcolor="white",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(visible=False, range=[0, max_v * 1.55]),
        )

        gid = f"ev-ann-{location_uuid[:8]}-{fk[:16]}"
        cards.append(
            html.Div(
                [header_row, dcc.Graph(id=gid, figure=fig, config={"displayModeBar": False})],
                className="mb-3 pb-2",
                style={"borderBottom": "1px solid #f0f4fb"},
            )
        )

    return html.Div(cards, className="mt-2") if cards else None


# ── Shared zone-ordering helper ───────────────────────────────────────────────


def _orden_zona(zona: str) -> int:
    zl = zona.lower()
    if "exterior" in zl or "calle" in zl:
        return 0
    if "tienda" in zl:
        return 1
    if "caja" in zl:
        return 2
    return 3


def _sort_zona_key(zona: str) -> tuple:
    """Sort key: semantic role first, then ascending numeric suffix, then alphabetical.
    Ensures 'Planta 0' < 'Planta 1', 'Caja 0' < 'Caja 1', etc."""
    rol = _orden_zona(zona)
    nums = [int(n) for n in re.findall(r"\d+", zona)]
    return (rol, nums[0] if nums else 999, zona.lower())


# ── New "Estado" redesign helpers ─────────────────────────────────────────────


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


_FEATURE_FA_ICONS = {
    "afluencia_metro_gran_via": "fas fa-train-subway",
    "afluencia_metro_callao": "fas fa-train-subway",
    "n_turistas_isocrona": "fas fa-passport",
    "n_pasajeros_crucero_dia": "fas fa-ship",
    "n_eventos_gran_via": "fas fa-calendar-check",
    "ev_vacaciones_escolares": "fas fa-school",
    "cal_escolar_is_break": "fas fa-school",
    "cal_escolar_dias_hasta": "fas fa-school",
}


def _icon_for_feature(fk: str) -> str:
    return _FEATURE_FA_ICONS.get(fk, "fas fa-satellite-dish")


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _render_signal_yoy_chart(
    df_k,
    fk,
    label,
    sublabel,
    color,
    uid,
    anio_actual,
    anio_prev,
    meses_es,
    agg_fn,
    fecha_max=None,
    ventana="semana",
):
    """
    12-month bar chart (Ene-Dic completo) + año anterior translúcido.
    Meses sin datos: barra gris con etiqueta 'Sin datos'.
    KPI % delta período actual vs anterior en el encabezado.
    """
    mes_pivot = df_k.groupby(["anio", "mes_num"])["value"].agg(agg_fn).reset_index()
    has_any_actual = not mes_pivot[mes_pivot["anio"] == anio_actual].empty
    if not has_any_actual:
        return None

    def _get(anio, mes):
        row = mes_pivot[(mes_pivot["anio"] == anio) & (mes_pivot["mes_num"] == mes)]
        return float(row["value"].iloc[0]) if not row.empty else None

    # ── 12 meses completos ──────────────────────────────────────────────────
    x_labels = meses_es  # todos Ene-Dic
    y_actual = [_get(anio_actual, m) for m in range(1, 13)]
    y_prev = [_get(anio_prev, m) for m in range(1, 13)]
    has_prev = any(v is not None and v > 0 for v in y_prev)
    missing = [v is None or v == 0 for v in y_actual]

    max_real = max((v for v in y_actual if v), default=1)
    ghost_h = max_real * 0.06

    y_disp = [v if (v and not missing[i]) else ghost_h for i, v in enumerate(y_actual)]
    bar_colors = [
        _hex_rgba(color, 0.88) if not missing[i] else "rgba(224,224,224,0.55)" for i in range(12)
    ]
    # % interanual por mes (actual vs mismo mes año anterior)
    yoy_pcts = []
    for i in range(12):
        pa = y_prev[i] if y_prev else None
        ya = y_actual[i]
        if not missing[i] and pa and pa > 0 and ya:
            yoy_pcts.append((ya - pa) / pa * 100)
        else:
            yoy_pcts.append(None)

    bar_text = []
    text_col = []
    for i, v in enumerate(y_actual):
        if missing[i]:
            bar_text.append("Sin datos")
            text_col.append("#aaaaaa")
            continue
        val_str = f"<b>{int(v):,}</b>" if v and v >= 1 else f"<b>{v:.1f}</b>"
        pct = yoy_pcts[i]
        if pct is not None:
            if abs(pct) < 0.5:
                bar_text.append(f"{val_str}<br>={pct:+.1f}%")
                text_col.append(_C_MUTED)
            elif pct > 0:
                bar_text.append(f"{val_str}<br>▲{pct:+.1f}%")
                text_col.append("#27ae60")
            else:
                bar_text.append(f"{val_str}<br>▼{pct:+.1f}%")
                text_col.append("#e74c3c")
        else:
            bar_text.append(val_str)
            text_col.append(_C_DARK)
    text_pos = ["outside" if not missing[i] else "inside" for i in range(12)]

    fig = go.Figure()
    if has_prev:
        y_prev_disp = [v if v else 0.0 for v in y_prev]
        fig.add_trace(
            go.Bar(
                name=str(anio_prev),
                x=x_labels,
                y=y_prev_disp,
                marker=dict(
                    color=_hex_rgba(color, 0.15), line=dict(color=color, width=1), cornerradius=5
                ),
                hovertemplate=[
                    (
                        f"{anio_prev} · {meses_es[i]}: <b>{int(y_prev[i]):,}</b><extra></extra>"
                        if y_prev[i]
                        else f"{anio_prev} · {meses_es[i]}: sin datos<extra></extra>"
                    )
                    for i in range(12)
                ],
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Bar(
            name=str(anio_actual),
            x=x_labels,
            y=y_disp,
            marker=dict(color=bar_colors, cornerradius=5),
            text=bar_text,
            textposition=text_pos,
            textfont=dict(size=9, color=text_col),
            hovertemplate=[
                (
                    f"{anio_actual} · {meses_es[i]}: <b>{int(y_actual[i]):,}</b><extra></extra>"
                    if not missing[i]
                    else f"{anio_actual} · {meses_es[i]}: sin datos<extra></extra>"
                )
                for i in range(12)
            ],
            showlegend=False,
        )
    )

    max_v = max(max_real, max((v for v in y_prev if v), default=0)) or 1
    fig.update_layout(
        barmode="group",
        height=230,
        margin=dict(t=10, b=10, l=10, r=10),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.70]),
        showlegend=False,
        bargap=0.22,
    )

    # ── KPI % delta período actual vs anterior ──────────────────────────────
    kpi_el = html.Span()
    if fecha_max is not None:
        try:
            dias_v = 28 if ventana == "mes" else 7
            fmax = pd.Timestamp(fecha_max)
            fmin_act = fmax - timedelta(days=dias_v - 1)
            fmin_ant = fmin_act - timedelta(days=dias_v)
            _df = df_k[df_k["anio"].isin([anio_actual, anio_prev])].copy()
            if "fecha" in _df.columns:
                act_s = _df.loc[(_df["fecha"] >= fmin_act) & (_df["fecha"] <= fmax), "value"]
                ant_s = _df.loc[(_df["fecha"] >= fmin_ant) & (_df["fecha"] < fmin_act), "value"]
                v_act = act_s.sum() if agg_fn == "sum" else (act_s.mean() if len(act_s) else 0)
                v_ant = ant_s.sum() if agg_fn == "sum" else (ant_s.mean() if len(ant_s) else 0)
                if v_ant > 0:
                    pct = (v_act - v_ant) / v_ant * 100
                    per_lbl = "mes" if ventana == "mes" else "semana"
                    val_txt = f"{int(v_act):,}" if v_act >= 1 else f"{v_act:.1f}"
                    if abs(pct) < 0.5:
                        kpi_el = html.Span(
                            f"{val_txt} este {per_lbl} · = {pct:+.1f}%",
                            style={"color": _C_MUTED, "fontSize": "0.76rem", "fontWeight": "600"},
                        )
                    else:
                        flecha = "▲" if pct > 0 else "▼"
                        kpi_color = "#27ae60" if pct > 0 else "#e74c3c"
                        kpi_el = html.Span(
                            f"{val_txt} este {per_lbl} · {flecha} {pct:+.1f}% vs {per_lbl} ant.",
                            style={"color": kpi_color, "fontSize": "0.76rem", "fontWeight": "600"},
                        )
        except Exception:
            pass

    # ── Leyenda años ────────────────────────────────────────────────────────
    def dot(op, bdr=""):
        return html.Span(
            style={
                "display": "inline-block",
                "width": "8px",
                "height": "8px",
                "background": color,
                "opacity": op,
                "border": bdr,
                "borderRadius": "1px",
                "marginRight": "4px",
            }
        )

    leyenda = html.Div(
        (
            [
                html.Div(
                    [
                        dot("0.88"),
                        html.Span(
                            str(anio_actual),
                            style={"fontSize": "0.67rem", "color": _C_DARK, "marginRight": "10px"},
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
                html.Div(
                    [
                        dot("0.2", f"1px solid {color}"),
                        html.Span(str(anio_prev), style={"fontSize": "0.67rem", "color": _C_MUTED}),
                    ],
                    className="d-flex align-items-center",
                ),
            ]
            if has_prev
            else []
        ),
        className="d-flex align-items-center gap-3 mb-1",
    )

    return html.Div(
        [
            html.Div(
                [
                    html.I(
                        className=f"{_icon_for_feature(fk)} me-2",
                        style={"color": color, "fontSize": "0.9rem"},
                    ),
                    html.Span(
                        label,
                        className="fw-semibold me-1",
                        style={"fontSize": "0.9rem", "color": _C_DARK},
                    ),
                    html.Span(sublabel, className="text-muted me-2", style={"fontSize": "0.74rem"}),
                    kpi_el,
                ],
                className="d-flex align-items-center flex-wrap gap-1 mb-1",
            ),
            leyenda,
            dcc.Graph(
                id=f"yoy-{uid}-{fk[:16]}", figure=fig, config=_CFG_GRAPH, style={"height": "230px"}
            ),
        ],
        className="mb-4",
    )


_SRC_COLOR: dict = {
    # Keys genéricos usados por los sources reales (evento_key en store_calendario_org)
    "concierto": "#e74c3c",
    "festival": "#f39c12",
    "deportivo": "#3498db",
    "evento_municipal": "#e67e22",
    "festivo_regional": "#27ae60",
    "vacaciones_escolares": "#8e44ad",
    "crucero": "#1abc9c",
    # Keys de Ticketmaster (prefijo tm_)
    "tm_concierto": "#e74c3c",
    "tm_festival": "#f39c12",
    "tm_deportivo": "#3498db",
    # Keys legacy del mock Showroom (mantener para datos históricos)
    "concierto_wizink": "#e74c3c",
    "estreno_callao": "#8e44ad",
    "festival_madrid": "#f39c12",
    "manifestacion_gran_via": "#e67e22",
    "partido_deportivo": "#3498db",
}
_SRC_LABEL: dict = {
    "concierto": "Concierto",
    "festival": "Festival",
    "deportivo": "Deportivo",
    "evento_municipal": "Municipal",
    "festivo_regional": "Festivo",
    "vacaciones_escolares": "Vacaciones",
    "crucero": "Crucero",
    "tm_concierto": "Concierto",
    "tm_festival": "Festival",
    "tm_deportivo": "Deportivo",
    "concierto_wizink": "Concierto",
    "estreno_callao": "Estreno",
    "festival_madrid": "Festival",
    "manifestacion_gran_via": "Manifestación",
    "partido_deportivo": "Deportivo",
}


def _meta_extra(src: str, meta: dict) -> str:
    """Resumen de metadata en una línea, según tipo de fuente."""
    parts = []
    if src == "crucero":
        pax = meta.get("n_pasajeros") or meta.get("pasajeros")
        if pax:
            parts.append(f"{int(pax):,} pax".replace(",", "."))
        terminal = meta.get("terminal")
        if terminal:
            parts.append(terminal)
    else:
        artista = meta.get("artista")
        if artista:
            parts.append(", ".join(artista[:2]) if isinstance(artista, list) else str(artista))
        venue = meta.get("venue_nombre") or meta.get("venue")
        if venue:
            parts.append(str(venue))
        aforo = meta.get("aforo")
        if aforo and not artista:
            parts.append(f"{int(aforo):,} aforo".replace(",", "."))
        rsvp = meta.get("rsvp_count") or meta.get("going")
        if rsvp and not aforo:
            parts.append(f"{int(rsvp):,} asistentes".replace(",", "."))
    return " · ".join(parts)


def _render_calendario_eventos_clima(location_uuid: str, fecha_max) -> html.Div | None:
    """
    CSS-grid calendar split by month. Each day cell: climate icons + one tag per
    event source (calendar events + cruise calls). Legend maps colors to sources.
    """
    import calendar as _cal

    try:
        from src.db.store import get_conn

        conn = get_conn()
        hoy_d = fecha_max.date() if hasattr(fecha_max, "date") else fecha_max
        desde_d = hoy_d - timedelta(days=56)
        hasta_d = hoy_d + timedelta(days=28)
        ev_rows = conn.execute(
            """SELECT evento_key, fecha_inicio, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND fecha_fin >= ? AND fecha_inicio <= ?
               ORDER BY fecha_inicio""",
            [location_uuid, str(desde_d), str(hasta_d)],
        ).fetchall()
        cl_rows = conn.execute(
            """SELECT feature_key, fecha::text, value
               FROM store_features_ext
               WHERE location_uuid = ? AND feature_key IN ('llueve','temp_max','temp_min')
                 AND fecha >= ? AND fecha <= ?""",
            [location_uuid, str(desde_d), str(hasta_d)],
        ).fetchall()
    except Exception:
        return None

    _IMPACT = {"alto": 3, "medio": 2, "bajo": 1}
    _CLEAN = str.maketrans({"—": " ", "–": " "})

    # day_events: date → list of {source, titulo, icono_fa, score, meta, fecha}
    day_events: dict = {}
    for key, fi, meta_json in ev_rows:
        fi_d = pd.to_datetime(fi).date()
        meta = (
            meta_json
            if isinstance(meta_json, dict)
            else (json.loads(meta_json) if meta_json else {})
        )
        is_vac = "vacaciones" in key.lower()
        # Normalize source for color lookup — any crucero-like key maps to 'crucero'
        src_key = "crucero" if "crucero" in key.lower() else key
        titulo_raw = (
            meta.get("titulo")
            or meta.get("nombre")
            or meta.get("barco")
            or key.replace("_", " ").title()
        )
        icono = (
            "fas fa-ship"
            if "crucero" in key.lower()
            else meta.get("icono_fa", "fas fa-calendar-day")
        )
        score_base = (
            1.5 if "crucero" in key.lower() else float(_IMPACT.get(meta.get("impacto", ""), 1))
        )
        day_events.setdefault(fi_d, []).append(
            dict(
                source=src_key,
                titulo=titulo_raw.translate(_CLEAN).strip(),
                icono_fa=icono,
                is_vacation=is_vac,
                score=0.5 if is_vac else score_base,
                meta=meta,
                fecha=fi_d,
            )
        )

    clima: dict = {}
    for fk, fecha, val in cl_rows:
        d = pd.to_datetime(fecha).date()
        clima.setdefault(d, {})[fk] = val

    if not day_events and not clima:
        return None

    _MES_ES = [
        "Enero",
        "Febrero",
        "Marzo",
        "Abril",
        "Mayo",
        "Junio",
        "Julio",
        "Agosto",
        "Septiembre",
        "Octubre",
        "Noviembre",
        "Diciembre",
    ]
    DIAS_HDR = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    months = []
    y, m = desde_d.year, desde_d.month
    while date(y, m, 1) <= hasta_d:
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    def _ev_tag(ev):
        c = _SRC_COLOR.get(ev["source"], "#7f8c8d")
        lbl = _SRC_LABEL.get(ev["source"], ev["source"].replace("_", " ").title())
        short = ev["titulo"][:24] + ("…" if len(ev["titulo"]) > 24 else "")
        extra = _meta_extra(ev["source"], ev.get("meta", {}))
        lines = [
            html.Span(
                f"{lbl} · {short}",
                style={
                    "fontSize": "0.60rem",
                    "lineHeight": "1.3",
                    "color": "#2c3e50",
                    "fontWeight": "500",
                },
            ),
        ]
        if extra:
            lines.append(
                html.Span(
                    extra, style={"fontSize": "0.56rem", "lineHeight": "1.2", "color": _C_MUTED}
                )
            )
        return html.Div(
            [
                html.Span(
                    style={
                        "display": "inline-block",
                        "width": "7px",
                        "height": "7px",
                        "borderRadius": "50%",
                        "background": c,
                        "flexShrink": "0",
                        "marginTop": "3px",
                    }
                ),
                html.Div(lines, className="d-flex flex-column"),
            ],
            className="d-flex align-items-start gap-1 mt-1",
        )

    def _day_cell(d):
        is_today = d == hoy_d
        evs = day_events.get(d, [])
        acts = sorted([e for e in evs if not e["is_vacation"]], key=lambda e: -e["score"])
        vac = [e for e in evs if e["is_vacation"]]

        # Border and background from top event's source
        if acts:
            bc = _SRC_COLOR.get(acts[0]["source"], "#7f8c8d")
            bg = _hex_rgba(bc, 0.06)
        elif vac:
            bc, bg = "#9b59b6", "#f3e5f5"
        else:
            bg = "#ffffff"
            bc = _C_PRIMARY if is_today else "#e9ecef"

        cl = clima.get(d, {})
        tmax = cl.get("temp_max", None)
        tmin = cl.get("temp_min", None)
        lluv = cl.get("llueve", 0) or 0
        if lluv > 0:
            w_cls, w_col = "fas fa-cloud-showers-heavy", "#3498db"
        elif tmax is not None and tmax >= 25:
            w_cls, w_col = "fas fa-sun", "#f39c12"
        elif tmax is not None and tmax < 12:
            w_cls, w_col = "fas fa-snowflake", "#74b9ff"
        else:
            w_cls, w_col = "fas fa-cloud-sun", "#95a5a6"
        temp_txt = f"{round(tmax)}°/{round(tmin)}°" if tmax is not None and tmin is not None else ""

        num_color = _C_PRIMARY if is_today else (_C_DARK if d <= hoy_d else "#555")
        cell_style = {
            "background": bg,
            "borderLeft": f"3px solid {bc}",
            "minHeight": "175px",
            "padding": "6px 8px",
            "borderRadius": "4px",
        }
        if is_today:
            cell_style["boxShadow"] = f"0 0 0 2px {_C_PRIMARY}"

        ev_content: list = [_ev_tag(e) for e in acts[:3]]
        if len(acts) > 3:
            ev_content.append(
                html.Div(
                    f"+{len(acts) - 3} más",
                    style={"fontSize": "0.57rem", "color": _C_MUTED, "marginLeft": "10px"},
                )
            )
        if not acts and vac:
            ev_content.append(
                html.Div(
                    html.I(
                        className="fas fa-school", style={"color": "#9b59b6", "fontSize": "0.62rem"}
                    ),
                    style={"marginTop": "3px"},
                )
            )

        return html.Div(
            [
                html.Div(
                    [
                        html.Span(
                            str(d.day),
                            style={"fontSize": "0.88rem", "fontWeight": "700", "color": num_color},
                        ),
                        html.I(
                            className=f"{w_cls} ms-1",
                            title=temp_txt,
                            style={"color": w_col, "fontSize": "0.72rem"},
                        ),
                        html.Span(
                            temp_txt, className="ms-1 text-muted", style={"fontSize": "0.60rem"}
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
                *ev_content,
            ],
            style=cell_style,
        )

    header_row = [
        html.Div(
            lbl,
            className="text-center fw-bold py-1 text-secondary bg-light",
            style={
                "fontSize": "0.70rem",
                "textTransform": "uppercase",
                "letterSpacing": "0.5px",
                "borderRadius": "3px",
            },
        )
        for lbl in DIAS_HDR
    ]

    tabs_meses = []
    for y, m in months:
        primer_dia = date(y, m, 1)
        ultimo_dia = date(y, m, _cal.monthrange(y, m)[1])
        grid_start = primer_dia - timedelta(days=primer_dia.weekday())
        grid_end = ultimo_dia + timedelta(days=6 - ultimo_dia.weekday())

        cells = list(header_row)
        d_iter = grid_start
        while d_iter <= grid_end:
            if d_iter.month != m:
                cells.append(
                    html.Div(
                        style={
                            "minHeight": "130px",
                            "background": "#f8f9fa",
                            "borderRadius": "4px",
                            "opacity": "0.4",
                        }
                    )
                )
            else:
                cells.append(_day_cell(d_iter))
            d_iter += timedelta(days=1)

        grilla = html.Div(
            cells,
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(7, 1fr)",
                "gap": "8px",
            },
        )
        tab_id = f"tab-{y}-{m}"
        tab_lbl = _MES_ES[m - 1] if y == hoy_d.year else f"{_MES_ES[m - 1]} {y}"
        tabs_meses.append(
            dbc.Tab(
                html.Div(grilla, className="pt-3"),
                label=tab_lbl,
                tab_id=tab_id,
                className="fw-bold",
            )
        )

    # ── Dynamic legend: only sources actually present in the window ─────
    present_sources = {e["source"] for evs in day_events.values() for e in evs}
    present_sources.discard("vacaciones_escolares")  # shown via icon only

    # Deduplicate: tm_concierto/tm_festival/tm_deportivo collapse to their generic form
    _ALIAS = {
        "tm_concierto": "concierto",
        "tm_festival": "festival",
        "tm_deportivo": "deportivo",
        "concierto_wizink": "concierto",
        "festival_madrid": "festival",
        "partido_deportivo": "deportivo",
        "manifestacion_gran_via": "evento_municipal",
        "estreno_callao": "concierto",
    }
    display_sources: dict[str, str] = {}  # canonical_key → display_label
    for src in present_sources:
        canon = _ALIAS.get(src, src)
        display_sources[canon] = _SRC_LABEL.get(src, src.replace("_", " ").title())

    legend_items = []
    for canon, lbl in sorted(display_sources.items(), key=lambda x: x[1]):
        c = _SRC_COLOR.get(canon, "#7f8c8d")
        legend_items.append(
            html.Div(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "8px",
                            "height": "8px",
                            "borderRadius": "50%",
                            "background": c,
                            "marginRight": "4px",
                            "flexShrink": "0",
                        }
                    ),
                    html.Span(lbl, style={"fontSize": "0.67rem", "color": _C_MUTED}),
                ],
                className="d-flex align-items-center me-3",
            )
        )

    legend_items.append(
        html.Div(
            [
                html.I(
                    className="fas fa-cloud-showers-heavy me-1",
                    style={"color": "#3498db", "fontSize": "0.67rem"},
                ),
                html.I(
                    className="fas fa-sun me-1", style={"color": "#f39c12", "fontSize": "0.67rem"}
                ),
                html.I(
                    className="fas fa-snowflake me-1",
                    style={"color": "#74b9ff", "fontSize": "0.67rem"},
                ),
                html.I(
                    className="fas fa-cloud-sun", style={"color": "#95a5a6", "fontSize": "0.67rem"}
                ),
            ],
            className="d-flex align-items-center",
        )
    )

    active_tab = f"tab-{hoy_d.year}-{hoy_d.month}"
    if tabs_meses and active_tab not in {t.tab_id for t in tabs_meses}:
        active_tab = tabs_meses[-1].tab_id

    return html.Div(
        [
            html.H6(
                "Calendario del entorno",
                className="fw-bold mb-2",
                style={"color": _C_DARK, "fontSize": "0.98rem"},
            ),
            html.Div(legend_items, className="d-flex flex-wrap gap-1 mb-3"),
            dbc.Tabs(tabs_meses, active_tab=active_tab),
        ]
    )


_ICONO_TIPO = {
    "concierto": "fas fa-music",
    "festival": "fas fa-calendar-star",
    "deportivo": "fas fa-futbol",
    "evento_municipal": "fas fa-city",
}
_NORM_TIPO = {
    "tm_concierto": "concierto",
    "tm_festival": "festival",
    "tm_deportivo": "deportivo",
    "concierto_wizink": "concierto",
    "festival_madrid": "festival",
    "partido_deportivo": "deportivo",
    "estreno_callao": "concierto",
    "manifestacion_gran_via": "evento_municipal",
}
_TIPOS_EXCLUIR = {
    "vacaciones_escolares",
    "festivo_regional",
    "ev_vacaciones_escolares",
    "ev_festivo_regional",
    "escala_crucero",
}


def _render_eventos_mensual_section(location_uuid: str, fecha_max) -> html.Div | None:
    """Monthly event-count bar charts (one per type), same visual pattern as cruise section."""
    try:
        from src.db.store import get_conn

        conn = get_conn()
        desde = fecha_max - timedelta(days=760)
        rows = conn.execute(
            """SELECT evento_key, fecha_inicio::text, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND fecha_inicio >= ?
               ORDER BY fecha_inicio""",
            [location_uuid, str(desde.date() if hasattr(desde, "date") else desde)],
        ).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["evento_key", "fecha", "metadata"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["tipo"] = df["evento_key"].map(lambda k: _NORM_TIPO.get(k, k))
    df["anio"] = df["fecha"].dt.year
    df["mes_num"] = df["fecha"].dt.month
    df = df[~df["tipo"].isin(_TIPOS_EXCLUIR)]

    if df.empty:
        return None

    anio_actual = fecha_max.year if hasattr(fecha_max, "year") else pd.Timestamp(fecha_max).year
    anio_prev = anio_actual - 1
    mes_hoy = date.today().month
    _MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    tipos = sorted(df["tipo"].unique(), key=lambda t: _SRC_LABEL.get(t, t))
    charts = []

    for tipo in tipos:
        color = _SRC_COLOR.get(tipo, "#7f8c8d")
        lbl = _SRC_LABEL.get(tipo, tipo.replace("_", " ").title())
        sub = df[df["tipo"] == tipo]

        mes_pivot = sub.groupby(["anio", "mes_num"]).size().reset_index(name="n")

        def _gv(yr, m):
            r = mes_pivot[(mes_pivot["anio"] == yr) & (mes_pivot["mes_num"] == m)]
            return int(r["n"].iloc[0]) if not r.empty else None

        y_act = [_gv(anio_actual, m) for m in range(1, 13)]
        y_prev = [_gv(anio_prev, m) for m in range(1, 13)]
        has_p = any(v for v in y_prev)

        if not any(v for v in y_act):
            continue

        missing = [v is None or v == 0 for v in y_act]
        max_act = max((v for v in y_act if v), default=1)
        max_prev = max((v for v in y_prev if v), default=0) if has_p else 0
        max_all = max(max_act, max_prev, 1)
        ghost_h = max_all * 0.06
        y_disp = [v if (v and not missing[i]) else ghost_h for i, v in enumerate(y_act)]
        bar_cols = [
            _hex_rgba(color, 0.88) if not missing[i] else "rgba(224,224,224,0.55)"
            for i in range(12)
        ]

        yoy_pcts = []
        for i in range(12):
            pa, ya = y_prev[i], y_act[i]
            yoy_pcts.append((ya - pa) / pa * 100 if (not missing[i] and pa and ya) else None)

        bar_text, text_col = [], []
        for i, v in enumerate(y_act):
            if missing[i]:
                bar_text.append("—")
                text_col.append("#aaaaaa")
                continue
            pct = yoy_pcts[i]
            if pct is not None:
                sign = "▲" if pct > 0 else "▼"
                bar_text.append(f"<b>{v}</b><br>{sign}{abs(pct):.0f}%")
                text_col.append("#27ae60" if pct > 0 else "#e74c3c")
            else:
                bar_text.append(f"<b>{v}</b>")
                text_col.append(_C_DARK)

        text_pos = ["outside" if not missing[i] else "inside" for i in range(12)]

        # Hover text for prev-year bars
        def plural(n):
            return "s" if n != 1 else ""

        prev_hover = [
            (
                f"{_MESES_ES[i]}: <b>{y_prev[i]}</b> {lbl.lower()}{plural(y_prev[i] or 0)}<extra></extra>"
                if y_prev[i]
                else f"{_MESES_ES[i]}: sin datos<extra></extra>"
            )
            for i in range(12)
        ]

        fig = go.Figure()
        if has_p:
            fig.add_trace(
                go.Bar(
                    x=_MESES_ES,
                    y=[v or 0 for v in y_prev],
                    name=str(anio_prev),
                    marker=dict(
                        color=_hex_rgba(color, 0.15),
                        line=dict(color=color, width=1),
                        cornerradius=5,
                    ),
                    hovertemplate=prev_hover,
                    showlegend=False,
                )
            )
        fig.add_trace(
            go.Bar(
                x=_MESES_ES,
                y=y_disp,
                name=str(anio_actual),
                marker=dict(color=bar_cols, cornerradius=5),
                text=bar_text,
                textposition=text_pos,
                textfont=dict(size=9, color=text_col),
                hovertemplate=[
                    (
                        f"{_MESES_ES[i]}: <b>{y_act[i]}</b> {lbl.lower()}{plural(y_act[i])}"
                        "<extra></extra>"
                        if not missing[i]
                        else f"{_MESES_ES[i]}: sin datos<extra></extra>"
                    )
                    for i in range(12)
                ],
                showlegend=False,
            )
        )
        fig.update_layout(
            barmode="group",
            height=220,
            margin=dict(t=20, b=10, l=10, r=10),
            plot_bgcolor="white",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, tickfont=dict(size=10), fixedrange=True),
            yaxis=dict(visible=False, fixedrange=True, range=[0, max_all * 1.60]),
            showlegend=False,
        )
        _vline_x = _MESES_ES[mes_hoy - 1]
        fig.add_shape(
            type="line",
            x0=_vline_x,
            x1=_vline_x,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line=dict(color="rgba(0,82,204,0.45)", width=1.5, dash="dot"),
        )
        fig.add_annotation(
            x=_vline_x,
            y=1.01,
            xref="x",
            yref="paper",
            text="hoy",
            showarrow=False,
            yanchor="bottom",
            font=dict(size=8, color="rgba(0,82,204,0.7)"),
        )

        # ── Event metadata lists for both years ────────────────────────────────
        def _ev_items(yr):
            rows_yr = sub[sub["anio"] == yr].sort_values("mes_num")
            items = []
            seen = set()
            for _, row in rows_yr.iterrows():
                meta = row.get("metadata") or {}
                title = (meta.get("titulo") or row["evento_key"])[:32]
                venue = (meta.get("venue") or "")[:22]
                key = (title, row["mes_num"])
                if key in seen:
                    continue
                seen.add(key)
                items.append((row["mes_num"], title, venue))
            return items

        def _ev_list_els(items, text_color):
            els = []
            for mes_n, title, venue in items[:6]:
                parts = [
                    html.Span(
                        _MESES_ES[mes_n - 1],
                        style={
                            "color": _C_MUTED,
                            "fontSize": "0.60rem",
                            "minWidth": "22px",
                            "display": "inline-block",
                        },
                    ),
                    html.Span(title, style={"fontSize": "0.62rem", "color": text_color}),
                ]
                if venue:
                    parts.append(
                        html.Span(f" · {venue}", style={"fontSize": "0.59rem", "color": _C_MUTED})
                    )
                els.append(html.Div(parts, className="d-flex align-items-center gap-1"))
            if len(items) > 6:
                els.append(
                    html.Span(
                        f"+{len(items)-6} más", style={"fontSize": "0.59rem", "color": _C_MUTED}
                    )
                )
            return els

        act_items = _ev_items(anio_actual)
        prev_items = _ev_items(anio_prev) if has_p else []

        def dot(op, bdr=""):
            return html.Span(
                style={
                    "display": "inline-block",
                    "width": "8px",
                    "height": "8px",
                    "background": color,
                    "opacity": op,
                    "flexShrink": 0,
                    "border": bdr,
                    "borderRadius": "1px",
                    "marginRight": "4px",
                }
            )

        def _year_block(yr_label, dot_el, items, text_color):
            header = html.Div(
                [
                    dot_el,
                    html.Span(
                        str(yr_label),
                        style={"fontSize": "0.67rem", "color": text_color, "fontWeight": "600"},
                    ),
                ],
                className="d-flex align-items-center mb-1",
            )
            return html.Div([header] + _ev_list_els(items, text_color), style={"minWidth": "160px"})

        legend_blocks = [
            _year_block(anio_actual, dot("0.88"), act_items, _C_DARK),
        ]
        if has_p and prev_items:
            legend_blocks.append(
                _year_block(anio_prev, dot("0.2", f"1px solid {color}"), prev_items, _C_MUTED)
            )
        leyenda = html.Div(legend_blocks, className="d-flex flex-wrap gap-4 mb-2")

        icono = _ICONO_TIPO.get(tipo, "fas fa-calendar-day")
        uid8 = location_uuid[:8]
        charts.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.I(
                                className=f"{icono} me-2",
                                style={"color": color, "fontSize": "0.9rem"},
                            ),
                            html.Span(
                                lbl,
                                className="fw-semibold",
                                style={"fontSize": "0.9rem", "color": _C_DARK},
                            ),
                        ],
                        className="d-flex align-items-center mb-1",
                    ),
                    leyenda,
                    dcc.Graph(
                        id=f"ev-{tipo}-{uid8}",
                        figure=fig,
                        config=_CFG_GRAPH,
                        style={"height": "200px"},
                    ),
                ],
                className="mb-4",
            )
        )

    return html.Div(charts) if charts else None


def _render_cruceros_section(
    location_uuid: str, fecha_max, ventana: str = "semana"
) -> html.Div | None:
    """12-month YoY passenger chart for cruise locations + % delta del período."""
    try:
        from src.db.store import get_conn

        conn = get_conn()
        desde_yoy = fecha_max - timedelta(days=760)
        yoy_rows = conn.execute(
            """SELECT e.fecha::text, e.value
               FROM store_features_ext e
               JOIN feature_flags f ON f.feature_key = e.feature_key
                 AND f.location_uuid = e.location_uuid AND f.status = 'active'
               WHERE e.location_uuid = ? AND e.feature_key = 'n_pasajeros_crucero_oficial'
                 AND e.value IS NOT NULL AND e.fecha >= ?
               ORDER BY e.fecha""",
            [location_uuid, str(desde_yoy.date() if hasattr(desde_yoy, "date") else desde_yoy)],
        ).fetchall()
    except Exception:
        return None

    if not yoy_rows:
        return None

    _MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    color = "#1abc9c"
    mes_hoy = date.today().month

    df_y = pd.DataFrame(yoy_rows, columns=["fecha", "value"])
    df_y["fecha"] = pd.to_datetime(df_y["fecha"])
    df_y["anio"] = df_y["fecha"].dt.year
    df_y["mes_num"] = df_y["fecha"].dt.month

    anio_actual = fecha_max.year if hasattr(fecha_max, "year") else pd.Timestamp(fecha_max).year
    anio_prev = anio_actual - 1

    if df_y[df_y["anio"] == anio_actual].empty:
        return None

    # Load ship metadata from the calendar store
    cruise_meta: dict[int, list[dict]] = {}  # {anio: [{mes_num, barco, pax}]}
    try:
        from src.db.store import get_conn as _gc

        meta_rows = (
            _gc()
            .execute(
                """SELECT fecha_inicio::text, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND evento_key = 'escala_crucero'
                 AND fecha_inicio >= ?
               ORDER BY fecha_inicio""",
                [location_uuid, str(desde_yoy.date() if hasattr(desde_yoy, "date") else desde_yoy)],
            )
            .fetchall()
        )
        for fecha_str, meta in meta_rows:
            if not meta:
                continue
            dt = pd.Timestamp(fecha_str)
            yr = dt.year
            mn = dt.month
            barco = (meta.get("barco") or "").strip()[:30]
            pax = meta.get("n_pasajeros") or meta.get("pasajeros") or 0
            cruise_meta.setdefault(yr, []).append({"mes_num": mn, "barco": barco, "pax": int(pax)})
    except Exception:
        pass

    mes_pivot = df_y.groupby(["anio", "mes_num"])["value"].sum().reset_index()

    def _gv(yr, m):
        r = mes_pivot[(mes_pivot["anio"] == yr) & (mes_pivot["mes_num"] == m)]
        return float(r["value"].iloc[0]) if not r.empty else None

    # Previsión de escalas futuras (store_calendario_org) para el año actual
    _mes_actual_num = date.today().month
    _fc_by_month: dict[int, float] = {}
    try:
        _fc_rows = conn.execute(
            """SELECT EXTRACT(MONTH FROM fecha_inicio::date)::int,
                      COALESCE(SUM(
                          CASE WHEN (metadata->>'n_pasajeros') ~ '^[0-9]+$'
                               THEN (metadata->>'n_pasajeros')::int ELSE 0 END
                      ), 0)
               FROM   store_calendario_org
               WHERE  location_uuid = ? AND evento_key = 'escala_crucero'
                 AND  fecha_inicio > CURRENT_DATE
                 AND  EXTRACT(YEAR FROM fecha_inicio::date)::int = ?
               GROUP  BY 1""",
            [location_uuid, anio_actual],
        ).fetchall()
        _fc_by_month = {int(m): float(v) for m, v in _fc_rows if v and v > 0}
    except Exception:
        pass

    y_act = [_gv(anio_actual, m) for m in range(1, 13)]
    y_prev = [_gv(anio_prev, m) for m in range(1, 13)]
    has_p = any(v for v in y_prev)

    # Niveles de fiabilidad por mes (afecta color y texto):
    #   'conf' — mes completo pasado, dato real
    #   'prog' — mes en curso, acumulado parcial
    #   'prev' — mes futuro, previsión del puerto
    #   'miss' — sin datos ni previsión
    def _tier(m: int) -> str:
        if y_act[m - 1] and y_act[m - 1] > 0:
            return "prog" if m >= _mes_actual_num else "conf"
        return "prev" if m in _fc_by_month else "miss"

    tiers = [_tier(m) for m in range(1, 13)]

    # Inyectar valores de previsión en y_act para que el gráfico los muestre
    for m in range(1, 13):
        if tiers[m - 1] == "prev":
            y_act[m - 1] = _fc_by_month[m]

    missing = [t == "miss" for t in tiers]

    max_act = max((v for v in y_act if v), default=1)
    max_prev = max((v for v in y_prev if v), default=0) if has_p else 0
    max_all = max(max_act, max_prev, 1)
    ghost_h = max_all * 0.06
    y_disp = [v if (v and not missing[i]) else ghost_h for i, v in enumerate(y_act)]
    _C_CONF = _hex_rgba(color, 0.88)  # real — meses completos pasados
    _C_PROG = _hex_rgba(color, 0.55)  # en curso — mes actual, parcial
    _C_PREV = _hex_rgba(color, 0.25)  # previsión — meses futuros
    _C_MISS = "rgba(224,224,224,0.55)"
    _tier_color = {"conf": _C_CONF, "prog": _C_PROG, "prev": _C_PREV, "miss": _C_MISS}
    bar_cols = [_tier_color[t] for t in tiers]
    # % interanual por mes (cruceros)
    cr_yoy_pcts = []
    for i in range(12):
        pa = y_prev[i]
        ya = y_act[i]
        if not missing[i] and pa and pa > 0 and ya:
            cr_yoy_pcts.append((ya - pa) / pa * 100)
        else:
            cr_yoy_pcts.append(None)

    bar_text = []
    text_col = []
    for i, v in enumerate(y_act):
        tier = tiers[i]
        if tier == "miss":
            bar_text.append("Sin datos")
            text_col.append("#aaaaaa")
            continue
        val_str = f"<b>{int(v):,}</b>" if v >= 1 else f"<b>{v:.0f}</b>"
        if tier == "prev":
            bar_text.append(f"{val_str}<br><i>prev.</i>")
            text_col.append(_C_MUTED)
            continue
        pct = cr_yoy_pcts[i]
        if pct is not None:
            if abs(pct) < 0.5:
                bar_text.append(f"{val_str}<br>={pct:+.1f}%")
                text_col.append(_C_MUTED)
            elif pct > 0:
                bar_text.append(f"{val_str}<br>▲{pct:+.1f}%")
                text_col.append("#27ae60")
            else:
                bar_text.append(f"{val_str}<br>▼{pct:+.1f}%")
                text_col.append("#e74c3c")
        else:
            bar_text.append(val_str)
            text_col.append(_C_DARK)
    text_pos = ["outside" if tier != "miss" else "inside" for tier in tiers]

    prev_hover = [
        (
            f"{_MESES_ES[i]}: <b>{int(y_prev[i]):,}</b> pax<extra></extra>"
            if y_prev[i]
            else f"{_MESES_ES[i]}: sin datos<extra></extra>"
        )
        for i in range(12)
    ]

    fig = go.Figure()
    if has_p:
        y_prev_d = [v if v else 0.0 for v in y_prev]
        fig.add_trace(
            go.Bar(
                x=_MESES_ES,
                y=y_prev_d,
                name=str(anio_prev),
                marker=dict(
                    color=_hex_rgba(color, 0.15), line=dict(color=color, width=1), cornerradius=5
                ),
                hovertemplate=prev_hover,
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Bar(
            x=_MESES_ES,
            y=y_disp,
            name=str(anio_actual),
            marker=dict(color=bar_cols, cornerradius=5),
            text=bar_text,
            textposition=text_pos,
            textfont=dict(size=9, color=text_col),
            hovertemplate=[
                (
                    f"{_MESES_ES[i]}: <b>{int(y_act[i]):,}</b> pax<extra></extra>"
                    if not missing[i]
                    else f"{_MESES_ES[i]}: sin datos<extra></extra>"
                )
                for i in range(12)
            ],
            showlegend=False,
        )
    )
    max_v = max_all or 1
    fig.update_layout(
        barmode="group",
        height=220,
        margin=dict(t=20, b=10, l=10, r=10),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, tickfont=dict(size=10), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.60]),
        showlegend=False,
    )
    _vline_x = _MESES_ES[mes_hoy - 1]
    fig.add_shape(
        type="line",
        x0=_vline_x,
        x1=_vline_x,
        y0=0,
        y1=1,
        xref="x",
        yref="paper",
        line=dict(color="rgba(0,82,204,0.45)", width=1.5, dash="dot"),
    )
    fig.add_annotation(
        x=_vline_x,
        y=1.01,
        xref="x",
        yref="paper",
        text="hoy",
        showarrow=False,
        yanchor="bottom",
        font=dict(size=8, color="rgba(0,82,204,0.7)"),
    )

    # % delta período
    kpi_el = html.Span()
    try:
        dias_v = 28 if ventana == "mes" else 7
        fmax = pd.Timestamp(fecha_max)
        fmin_act = fmax - timedelta(days=dias_v - 1)
        fmin_ant = fmin_act - timedelta(days=dias_v)
        v_act = df_y.loc[(df_y["fecha"] >= fmin_act) & (df_y["fecha"] <= fmax), "value"].sum()
        v_ant = df_y.loc[(df_y["fecha"] >= fmin_ant) & (df_y["fecha"] < fmin_act), "value"].sum()
        per_lbl = "mes" if ventana == "mes" else "semana"
        val_txt = f"{int(v_act):,}"
        if v_ant > 0:
            pct = (v_act - v_ant) / v_ant * 100
            if abs(pct) < 0.5:
                kpi_el = html.Span(
                    f"{val_txt} pax este {per_lbl} · = {pct:+.1f}%",
                    style={"color": _C_MUTED, "fontSize": "0.76rem", "fontWeight": "600"},
                )
            else:
                flecha = "▲" if pct > 0 else "▼"
                kpi_color = "#27ae60" if pct > 0 else "#e74c3c"
                kpi_el = html.Span(
                    f"{val_txt} pax este {per_lbl} · {flecha} {pct:+.1f}% vs {per_lbl} ant.",
                    style={"color": kpi_color, "fontSize": "0.76rem", "fontWeight": "600"},
                )
    except Exception:
        pass

    def dot(op, bdr=""):
        return html.Span(
            style={
                "display": "inline-block",
                "width": "8px",
                "height": "8px",
                "background": color,
                "opacity": op,
                "flexShrink": 0,
                "border": bdr,
                "borderRadius": "1px",
                "marginRight": "4px",
            }
        )

    def _cruise_list_els(yr, text_color):
        ships = sorted(cruise_meta.get(yr, []), key=lambda x: x["mes_num"])
        seen = set()
        els = []
        for s in ships[:6]:
            key = (s["barco"], s["mes_num"])
            if key in seen or not s["barco"]:
                continue
            seen.add(key)
            pax_txt = f"{s['pax']:,}".replace(",", ".") if s["pax"] else ""
            parts = [
                html.Span(
                    _MESES_ES[s["mes_num"] - 1],
                    style={
                        "color": _C_MUTED,
                        "fontSize": "0.60rem",
                        "minWidth": "22px",
                        "display": "inline-block",
                    },
                ),
                html.Span(s["barco"], style={"fontSize": "0.62rem", "color": text_color}),
            ]
            if pax_txt:
                parts.append(
                    html.Span(f" · {pax_txt} pax", style={"fontSize": "0.59rem", "color": _C_MUTED})
                )
            els.append(html.Div(parts, className="d-flex align-items-center gap-1"))
        remainder = len(set((s["barco"], s["mes_num"]) for s in ships if s["barco"])) - len(seen)
        if remainder > 0:
            els.append(
                html.Span(f"+{remainder} más", style={"fontSize": "0.59rem", "color": _C_MUTED})
            )
        return els

    def _year_block(yr_label, dot_el, text_color):
        header = html.Div(
            [
                dot_el,
                html.Span(
                    str(yr_label),
                    style={"fontSize": "0.67rem", "color": text_color, "fontWeight": "600"},
                ),
            ],
            className="d-flex align-items-center mb-1",
        )
        return html.Div(
            [header] + _cruise_list_els(yr_label, text_color), style={"minWidth": "160px"}
        )

    legend_blocks = [_year_block(anio_actual, dot("0.88"), _C_DARK)]
    if has_p and cruise_meta.get(anio_prev):
        legend_blocks.append(_year_block(anio_prev, dot("0.2", f"1px solid {color}"), _C_MUTED))

    leyenda = html.Div(legend_blocks, className="d-flex flex-wrap gap-4 mb-2")

    has_prev_tier = any(t == "prev" for t in tiers)
    nota_fuente = html.Div(
        [
            html.I(className="fas fa-circle-info me-1", style={"fontSize": "0.65rem"}),
            html.Span(
                "Fuente: Puertos del Estado · estadística oficial mensual. "
                + (
                    "Los meses futuros (más claros) muestran la previsión contractual "
                    "del Puerto de Málaga, disponible antes del cierre oficial."
                    if has_prev_tier
                    else "Datos publicados con aprox. 4-6 semanas de retraso sobre el cierre del mes."
                ),
            ),
        ],
        style={
            "fontSize": "0.62rem",
            "color": _C_MUTED,
            "marginTop": "4px",
            "lineHeight": "1.4",
        },
    )

    return html.Div(
        [
            html.Div(
                [
                    html.I(
                        className="fas fa-ship me-2", style={"color": color, "fontSize": "0.9rem"}
                    ),
                    html.Span(
                        "Pasajeros de crucero",
                        className="fw-semibold me-2",
                        style={"fontSize": "0.9rem", "color": _C_DARK},
                    ),
                    kpi_el,
                ],
                className="d-flex align-items-center flex-wrap gap-1 mb-1",
            ),
            leyenda,
            dcc.Graph(
                id=f"crucero-yoy-{location_uuid[:8]}",
                figure=fig,
                config=_CFG_GRAPH,
                style={"height": "200px"},
            ),
            nota_fuente,
        ],
        className="mb-4",
    )


def _render_senal_contexto_modal(
    location_uuid: str, uid: str, fecha_max, ventana: str = "semana"
) -> html.Div | None:
    """External signals modal: YoY bar charts per feature + events feed."""
    if not location_uuid:
        return None
    try:
        from src.db.store import get_conn

        conn = get_conn()
        desde = fecha_max - timedelta(days=760)
        ts_rows = conn.execute(
            """SELECT e.feature_key, e.fecha::text, e.value
               FROM store_features_ext e
               JOIN feature_flags f
                 ON f.feature_key = e.feature_key
                AND f.location_uuid = e.location_uuid
                AND f.status = 'active'
               WHERE e.location_uuid = ? AND e.value IS NOT NULL AND e.fecha >= ?
               ORDER BY e.feature_key, e.fecha""",
            [location_uuid, str(desde)],
        ).fetchall()
    except Exception:
        return None

    _MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    anio_actual = fecha_max.year
    anio_prev = anio_actual - 1

    charts = []
    if ts_rows:
        df_ts = pd.DataFrame(ts_rows, columns=["feature_key", "fecha", "value"])
        df_ts["fecha"] = pd.to_datetime(df_ts["fecha"])
        df_ts["anio"] = df_ts["fecha"].dt.year
        df_ts["mes_num"] = df_ts["fecha"].dt.month

        keys = [
            k
            for k in df_ts["feature_key"].unique()
            if k not in _UNIVERSAL_KEYS and k != "n_pasajeros_crucero_dia"
        ]
        metro_keys = sorted([k for k in keys if "metro" in k])
        other_keys = sorted([k for k in keys if k not in metro_keys])

        for fk in metro_keys + other_keys:
            meta = _FEATURE_META.get(fk, (fk.replace("_", " ").title(), "", "sum", _DEFAULT_COLOR))
            label, sublabel, agg_fn, color = meta
            if "gran_via" in fk:
                station = "Gran Vía: validaciones diarias"
                sub = "Línea 1 (azul) · Línea 5 (verde)"
            elif "callao" in fk:
                station = "Callao: validaciones diarias"
                sub = "Línea 3 (amarilla) · Línea 5 (verde)"
            else:
                station, sub = label, sublabel
            c = _render_signal_yoy_chart(
                df_ts[df_ts["feature_key"] == fk],
                fk,
                station,
                sub,
                color,
                uid,
                anio_actual,
                anio_prev,
                _MESES_ES,
                agg_fn,
                fecha_max=fecha_max,
                ventana=ventana,
            )
            if c:
                charts.append(c)

    cal_section = _render_calendario_eventos_clima(location_uuid, fecha_max)
    cruceros_section = _render_cruceros_section(location_uuid, fecha_max, ventana)
    eventos_mensual_section = _render_eventos_mensual_section(location_uuid, fecha_max)

    if not charts and not cal_section and not cruceros_section and not eventos_mensual_section:
        return None

    return html.Div(
        [
            *(
                [
                    html.Div(
                        [
                            html.H6(
                                "Afluencia en el entorno · comparativa interanual",
                                className="fw-bold mb-1",
                                style={"color": _C_DARK, "fontSize": "0.98rem"},
                            ),
                            html.P(
                                f"Barras sólidas = {anio_actual} · barras translúcidas = {anio_prev}. "
                                "Agregación mensual.",
                                className="text-muted mb-3",
                                style={"fontSize": "0.80rem"},
                            ),
                            html.Div(charts),
                        ]
                    )
                ]
                if charts
                else []
            ),
            *(
                [html.Div([html.Hr(className="my-4"), cruceros_section])]
                if cruceros_section
                else []
            ),
            *(
                [html.Div([html.Hr(className="my-4"), eventos_mensual_section])]
                if eventos_mensual_section
                else []
            ),
            *([html.Div([html.Hr(className="my-4"), cal_section])] if cal_section else []),
        ]
    )


def _render_zona_section_jerarquica(
    zonas_data, zona_children_map, child_zone_names, uid, periodo_label
) -> html.Div:
    """Zone cards: parent zones first (blue accent), children grouped below each parent."""
    parent_zones = sorted(
        [z for z in zonas_data if z["zona"] not in child_zone_names],
        key=lambda z: _sort_zona_key(z["zona"]),
    )

    if not zona_children_map:
        cols = [
            dbc.Col(
                _render_zona_card(
                    z["zona"],
                    z["r"],
                    z["a"],
                    z["d"],
                    z["dias_28"],
                    uid,
                    periodo_label,
                    has_children=False,
                    gap_actual=z.get("gap_actual", False),
                    gap_anterior=z.get("gap_anterior", False),
                ),
                xs=12,
                sm=6,
                xl=3,
                className="mb-3",
            )
            for z in sorted(zonas_data, key=lambda z: _sort_zona_key(z["zona"]))
        ]
        return dbc.Row(cols, className="g-3")

    sections = []
    for pz in parent_zones:
        children_names = zona_children_map.get(pz["zona"], [])
        children_data = [z for z in zonas_data if z["zona"] in children_names]

        parent_card = _render_zona_card(
            pz["zona"],
            pz["r"],
            pz["a"],
            pz["d"],
            pz["dias_28"],
            uid,
            periodo_label,
            child_names=None,
            has_children=bool(children_names),
            gap_actual=pz.get("gap_actual", False),
            gap_anterior=pz.get("gap_anterior", False),
        )

        block = [dbc.Row([dbc.Col(parent_card, xs=12)], className="mb-2 g-2")]

        if children_data:
            child_cols = [
                dbc.Col(
                    _render_zona_card(
                        cz["zona"],
                        cz["r"],
                        cz["a"],
                        cz["d"],
                        cz["dias_28"],
                        uid,
                        periodo_label,
                        has_children=False,
                        gap_actual=cz.get("gap_actual", False),
                        gap_anterior=cz.get("gap_anterior", False),
                    ),
                    xs=12,
                    sm=6,
                    className="mb-2",
                )
                for cz in sorted(children_data, key=lambda z: _sort_zona_key(z["zona"]))
            ]
            block.append(
                html.Div(
                    dbc.Row(child_cols, className="g-2"),
                    className="ps-4",
                    style={
                        "borderLeft": f"3px solid {_color_zona(pz['zona'])}",
                        "marginLeft": "8px",
                    },
                )
            )
        sections.append(html.Div(block, className="mb-4"))

    return html.Div(sections)


# ── Main assembly ─────────────────────────────────────────────────────────────


def generar_mensajes_salud(df, ubi, zonas_seleccionadas=None, location_uuid=None, ventana="semana"):
    if df.empty:
        return dbc.Alert("Ausencia de datos.", color="warning", className="rounded-4")

    zonas_validas = obtener_zonas_validas()
    if zonas_validas:
        df = df[df["Zona"].isin(zonas_validas)]
    if zonas_seleccionadas:
        df = df[df["Zona"].isin(zonas_seleccionadas)]
    if df.empty:
        return dbc.Alert("Ausencia de datos en la selección.", color="info", className="rounded-4")

    df = df.copy()
    # Excluir zonas sin nombre o con nombre de fallback ('SinNombre', vacías, NaN)
    _nombres_invalidos = {"sinnombre", "", "nan", "none"}
    df = df[
        df["Zona"].notna()
        & (~df["Zona"].astype(str).str.strip().str.lower().isin(_nombres_invalidos))
    ]
    if df.empty:
        return dbc.Alert(
            "Sin zonas con nombre válido para esta ubicación.", color="info", className="rounded-4"
        )

    df["fecha_dt"] = pd.to_datetime(df["fecha"]).dt.date
    fecha_max = df["fecha_dt"].max()
    if pd.isna(fecha_max):
        return dbc.Alert("Error de formato de fecha.", color="danger", className="rounded-4")

    lat, lon, _ = obtener_info_ubicacion(ubi)
    clima = obtener_clima_historico(
        lat,
        lon,
        (fecha_max - timedelta(days=60)).strftime("%Y-%m-%d"),
        fecha_max.strftime("%Y-%m-%d"),
    )

    uid = _slug(location_uuid or ubi)
    dias_v = 28 if ventana == "mes" else 7
    periodo_label = "mes" if ventana == "mes" else "semana"

    # ── Jerarquía de zonas ───────────────────────────────────────────────
    zona_children_map: dict[str, list[str]] = {}
    child_zone_names: set[str] = set()
    for parent_name, child_dicts in _dm.mapa_hijos_por_zona.get(location_uuid or "", {}).items():
        names = [z["value"] for z in child_dicts]
        if names:
            zona_children_map[parent_name] = names
            child_zone_names.update(names)

    # ── Datos por zona ───────────────────────────────────────────────────
    puntos = 0
    zonas_data = []
    for zona in df["Zona"].unique():
        dz = df[df["Zona"] == zona]
        r7, a7, d7, fmin7, fmax7, dias7 = evaluar_periodo_zona(dz, fecha_max, 7)
        r28, a28, d28, fmin28, fmax28, dias28 = evaluar_periodo_zona(dz, fecha_max, 28)

        r_p = r28 if ventana == "mes" else r7
        a_p = a28 if ventana == "mes" else a7
        d_p = d28 if ventana == "mes" else d7
        dias_p = dias28 if ventana == "mes" else dias7

        dias_28_raw = (
            dz[dz["fecha_dt"] >= fecha_max - timedelta(days=27)]
            .groupby("fecha_dt")["unique_visitors"]
            .sum()
            .reset_index()
            if "unique_visitors" in dz.columns
            else pd.DataFrame()
        )
        if not dias_28_raw.empty:
            dias_28 = dias_28_raw.copy()
            dias_28["unique_visitors"] = dias_28["unique_visitors"].replace(0, np.nan)
        else:
            dias_28 = dias_28_raw

        fmin_p = fecha_max - timedelta(days=dias_v - 1)
        fmin_a = fmin_p - timedelta(days=dias_v)
        fmax_a = fmin_p - timedelta(days=1)
        pct_p = _pct_activos(dz, fmin_p, fecha_max)
        pct_a = _pct_activos(dz, fmin_a, fmax_a)
        gap_actual = pct_p < 0.5
        gap_anterior = pct_a < 0.5

        if d_p["visitantes"] >= 5:
            puntos += 1
        elif d_p["visitantes"] <= -5:
            puntos -= 1

        zonas_data.append(
            dict(
                zona=zona,
                r=r_p,
                a=a_p,
                d=d_p,
                dias_p=dias_p,
                r7=r7,
                a7=a7,
                d7=d7,
                fmin7=fmin7,
                fmax7=fmax7,
                dias7=dias7,
                r28=r28,
                a28=a28,
                d28=d28,
                dias_28=dias_28,
                gap_actual=gap_actual,
                gap_anterior=gap_anterior,
            )
        )

    zonas_data_top = [z for z in zonas_data if z["zona"] not in child_zone_names] or zonas_data

    # ── Health status ────────────────────────────────────────────────────
    if puntos >= 1:
        health_label, badge_color = "Tendencia positiva", "success"
    elif puntos <= -1:
        health_label, badge_color = "Tendencia negativa", "danger"
    else:
        health_label, badge_color = "Tendencia estable", "warning"

    health_badge_id = f"pm-health-{uid}"
    n_zonas = len(zonas_data)
    health_tooltip = (
        f"Score calculado sobre {n_zonas} zona{'s' if n_zonas != 1 else ''}: "
        f"+1 por cada zona con δ visitantes ≥ +5 %, "
        f"−1 por cada zona con δ ≤ −5 %. "
        f"Score total: {puntos:+d}."
    )

    # ── Geo data ─────────────────────────────────────────────────────────
    geo_vals_loc = get_geo_vals(location_uuid) if location_uuid else {}
    fecha_captura = get_geo_snapshot_date(location_uuid) if location_uuid else None

    # ── Eventos de alto impacto (para narrativa) ─────────────────────────
    fmin_p_narr = fecha_max - timedelta(days=dias_v - 1)
    eventos_narr = (
        _eventos_narrativa(location_uuid, fmin_p_narr, fecha_max) if location_uuid else None
    )

    # ── Narrativa ────────────────────────────────────────────────────────
    items_narrativa = _narrativa(
        zonas_data_top,
        fecha_max,
        clima,
        ventana=ventana,
        geo_vals=geo_vals_loc,
        location_uuid=location_uuid,
        eventos=eventos_narr,
    )

    # ── Header ───────────────────────────────────────────────────────────
    header = dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.P(
                                "ESTADO",
                                className="mb-1 text-white-50 text-uppercase fw-bold",
                                style={"fontSize": "0.61rem", "letterSpacing": "1px"},
                            ),
                            html.H4(ubi, className="fw-bold mb-1 text-white"),
                            html.P(
                                f"{(fecha_max - timedelta(days=dias_v - 1)).strftime('%d %b')} – "
                                f"{fecha_max.strftime('%d %b %Y')}",
                                className="mb-0",
                                style={
                                    "fontSize": "0.84rem",
                                    "color": "rgba(255,255,255,0.82)",
                                    "fontWeight": "500",
                                },
                            ),
                        ],
                        xs=9,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                dbc.Badge(
                                    health_label,
                                    color=badge_color,
                                    pill=True,
                                    className="fs-6 px-3 py-2",
                                    id=health_badge_id,
                                    style={"cursor": "help"},
                                ),
                                dbc.Tooltip(
                                    health_tooltip, target=health_badge_id, placement="left"
                                ),
                            ],
                            className="d-flex justify-content-end align-items-center h-100",
                        ),
                        xs=3,
                    ),
                ]
            )
        ),
        className="border-0 rounded-4 mb-4 shadow-sm",
        style={"background": "linear-gradient(135deg, #0052CC 0%, #003d99 100%)"},
    )

    # ── PDF header (print-only) ───────────────────────────────────────────
    zonas_txt = ", ".join(zonas_seleccionadas or []) or "Todas las zonas analíticas"
    pdf_header = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H2(
                                "INFORME DE RENDIMIENTO OPERATIVO",
                                className="fw-bold text-dark mb-1",
                            ),
                            html.H5(
                                f"UBICACIÓN: {ubi.upper()}", className="text-secondary fw-bold mb-0"
                            ),
                        ],
                        width=8,
                    ),
                    dbc.Col(
                        [
                            html.P(
                                f"Emitido: {pd.Timestamp('today').strftime('%d/%m/%Y')}",
                                className="text-end text-muted mb-0 small fw-bold",
                            ),
                            html.P(
                                f"Datos hasta: {fecha_max.strftime('%d/%m/%Y')}",
                                className="text-end text-muted mb-0 small",
                            ),
                        ],
                        width=4,
                        className="d-flex flex-column justify-content-center",
                    ),
                ],
                className="mb-3",
            ),
            html.P([html.Strong("Segmentación: "), zonas_txt], className="mb-2"),
            html.Hr(style={"borderTop": "3px solid #2c3e50", "opacity": "1"}),
            html.Br(),
        ],
        className="d-none d-print-block",
    )

    # ── Narrativa (briefing siempre visible) ─────────────────────────────

    narrativa = html.Div(
        [
            html.H5(
                [html.I(className="fas fa-comment-dots me-2 text-primary"), "Resumen ejecutivo"],
                className="fw-bold mb-1",
                style={"fontSize": "1.05rem", "color": _C_DARK},
            ),
            html.P(
                (
                    "Análisis de los últimos 28 días vs los 28 días anteriores."
                    if ventana == "mes"
                    else "Análisis de los últimos 7 días vs los 7 días anteriores."
                ),
                className="text-muted mb-2",
                style={"fontSize": "0.84rem"},
            ),
            _render_narrativa(items_narrativa),
        ],
        className="mb-3",
    )

    # ── Contenidos de las secciones desplegables ──────────────────────────

    _ventana_zona_lbl = "últimos 28 días" if ventana == "mes" else "últimos 7 días"

    sec_zona = html.Div(
        [
            html.P(
                "Variación de visitantes respecto al período equivalente anterior. "
                "Las zonas padre se muestran con fondo azul; sus subzonas aparecen agrupadas debajo.",
                className="text-muted mb-3",
                style={"fontSize": "0.82rem"},
            ),
            _render_zona_section_jerarquica(
                zonas_data, zona_children_map, child_zone_names, uid, periodo_label
            ),
        ]
    )

    sec_patrones = html.Div(
        [
            html.P(
                "Distribución temporal de visitantes por día, hora y tipo de jornada.",
                className="text-muted mb-3",
                style={"fontSize": "0.82rem"},
            ),
            _render_pm_questions(
                df,
                zonas_data,
                fecha_max,
                uid,
                ventana=ventana,
                child_zones=child_zone_names,
                clima=clima,
            ),
        ]
    )

    sec_senales = _render_senal_contexto_modal(location_uuid, uid, fecha_max, ventana) or html.Div(
        html.P("Sin datos de contexto externo disponibles.", className="text-muted")
    )

    sec_geo = (
        generar_panel_geo_visual(location_uuid, geo_vals_loc, clima, fecha_captura=fecha_captura)
        if location_uuid
        else html.Div(html.P("Sin datos de contexto geoespacial.", className="text-muted"))
    )

    # ── Acordeón ─────────────────────────────────────────────────────────

    def _acc_title(icon_cls, texto, color):
        return html.Span(
            [
                html.I(className=f"{icon_cls} me-2", style={"color": color, "fontSize": "0.9rem"}),
                html.Span(
                    texto, style={"fontWeight": "600", "fontSize": "0.92rem", "color": _C_DARK}
                ),
            ]
        )

    acordeon = dbc.Accordion(
        [
            dbc.AccordionItem(
                sec_zona,
                title=_acc_title(
                    "fas fa-layer-group", f"Estado por zona · {_ventana_zona_lbl}", "#0052CC"
                ),
                item_id="zona",
            ),
            dbc.AccordionItem(
                sec_patrones,
                title=_acc_title("fas fa-chart-column", "Patrones de comportamiento", "#27AE60"),
                item_id="patrones",
            ),
            dbc.AccordionItem(
                sec_senales,
                title=_acc_title(
                    "fas fa-broadcast-tower", "Señal del contexto exterior", "#E67E22"
                ),
                item_id="senales",
            ),
            dbc.AccordionItem(
                sec_geo,
                title=_acc_title("fas fa-map-marked-alt", "Contexto geoespacial", "#8E44AD"),
                item_id="geo",
            ),
        ],
        always_open=True,
        active_item=[],
        className="pm-acordeon shadow-sm rounded-4",
    )

    return html.Div(
        [
            pdf_header,
            header,
            narrativa,
            acordeon,
        ]
    )


def generar_panel_pm(df_completo, locs, zonas_sel, ventana="semana"):
    if df_completo is None or df_completo.empty:
        return dbc.Alert("Sincroniza los datos.", color="warning", className="rounded-4")
    if not locs:
        return dbc.Alert("Selecciona una ubicación.", color="info", className="rounded-4")

    paneles = []
    for ubi in df_completo[df_completo["location_id"].isin(locs)]["Ubicación"].unique():
        df_ubi = df_completo[df_completo["Ubicación"] == ubi]
        loc_uuid = df_ubi["location_id"].iloc[0] if "location_id" in df_ubi.columns else None
        paneles.append(generar_mensajes_salud(df_ubi, ubi, zonas_sel, loc_uuid, ventana=ventana))
    return html.Div(paneles)
