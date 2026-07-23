"""
Chart builders for the Health Check panel.

All ``_fig_*`` functions and the shared climate-series helper live here.
Imported back into health_check.py so external callers are unaffected.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.core.theme import C_AMBER as _C_AMBER  # noqa: F401 – available for callers
from src.core.theme import C_DANGER as _C_DANGER
from src.core.theme import C_DARK as _C_DARK
from src.core.theme import C_MUTED as _C_MUTED
from src.core.theme import C_PRIMARY as _C_PRIMARY
from src.core.theme import C_SUCCESS as _C_SUCCESS

# Re-exported from health_check at import time — the lists are small constants.
dias_corto = ["L", "M", "X", "J", "V", "S", "D"]


def _rgba(hex_color: str, opacity: float) -> str:
    """Convierte un color HEX a rgba(R,G,B,opacity) para usar en trazas Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{opacity:.2f})"


# ── Shared helpers ────────────────────────────────────────────────────────────


def _date_windows(fecha_max: date, dias: int) -> tuple[date, date, date, date]:
    """Return (fmin_act, fecha_max, fmin_ant, fmax_ant) for the two consecutive windows."""
    fmin_act = fecha_max - timedelta(days=dias - 1)
    fmin_ant = fmin_act - timedelta(days=dias)
    fmax_ant = fmin_act - timedelta(days=1)
    return fmin_act, fecha_max, fmin_ant, fmax_ant


def _build_climate_serie(dias_dict: dict, s: date, e: date, key: str) -> list:
    """
    Build a list of per-day dicts covering [s, e] with 'lbl', 'vis', and one
    climate key drawn from *dias_dict*.

    Parameters
    ----------
    dias_dict : dict
        Pre-built dict of ``{date: {"lbl", "vis", key: value}}``.  Populated
        by the caller so this helper stays pure (no df access).
    s, e      : inclusive date window.
    key       : climate key name (``"tmax"`` or ``"precip"``).
    """
    _dias_es = {0: "L", 1: "M", 2: "X", 3: "J", 4: "V", 5: "S", 6: "D"}
    rows = []
    cur = s
    while cur <= e:
        entry = dias_dict.get(cur, {})
        rows.append(entry)
        cur += timedelta(days=1)
    return rows


# ── Sparkline ─────────────────────────────────────────────────────────────────


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


# ── Day-of-week distribution ──────────────────────────────────────────────────


def _fig_dias_semana(df_todas_zonas, fecha_max, dias=28, primary_color: str = _C_PRIMARY):
    """Distribución por día de la semana — período actual (sólido) vs anterior (translúcido)."""
    if df_todas_zonas.empty or "unique_visitors" not in df_todas_zonas.columns:
        return None

    fmin_act, _, fmin_ant, fmax_ant = _date_windows(fecha_max, dias)

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
    bar_colors = [_rgba(primary_color, 0.22 + 0.68 * r) for r in ratios]
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
                    color=_rgba(primary_color, 0.14),
                    line=dict(color=_rgba(primary_color, 0.35), width=1),
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


# ── Weekend vs weekday ────────────────────────────────────────────────────────


def _fig_finde_vs_laborable(df_todas_zonas, fecha_max, dias=28, primary_color: str = _C_PRIMARY):
    """Promedio visitantes/día: entre semana vs fin de semana — actual (sólido) vs anterior (translúcido)."""
    if df_todas_zonas.empty or "unique_visitors" not in df_todas_zonas.columns:
        return None

    fmin_act, _, fmin_ant, fmax_ant = _date_windows(fecha_max, dias)

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
    colors_act = [primary_color, "#e67e22"]
    colors_ant = [_rgba(primary_color, 0.15), "rgba(230,126,34,0.15)"]
    border_ant = [primary_color, "#e67e22"]

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


# ── Dwell time by zone ────────────────────────────────────────────────────────


def _fig_dwell_zonas(
    zonas_data, child_zones=None, color_fn: Callable | None = None, primary_color: str = _C_PRIMARY
):
    """Tiempo medio de permanencia por zona — solo zonas padre."""
    _cz = child_zones or set()
    _get_color = color_fn if color_fn is not None else (lambda z: primary_color)
    data = [
        (z["zona"], z["r"]["estancia"], _get_color(z["zona"]))
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


# ── Conversion funnel ─────────────────────────────────────────────────────────


def _fig_embudo_conversion(
    zonas_data, color_fn: Callable | None = None, primary_color: str = _C_PRIMARY
):
    """
    Embudo exterior → tienda → caja con tasa de conversión entre pasos.
    Requiere al menos dos zonas con roles distintos identificables.
    """
    _get_color = color_fn if color_fn is not None else (lambda z: primary_color)

    def _rol(z):
        ze = z.get("zone_enum")
        if ze is not None:
            return {2: 0, 1: 1, 0: 2}.get(ze, 99)
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
    colors = [_get_color(z["zona"]) for z in pasos]
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


# ── Peak hour ─────────────────────────────────────────────────────────────────


def _parse_hourly_pm(val):
    import json

    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        parsed = json.loads(str(val))
        if isinstance(parsed, list) and len(parsed) == 24:
            return [float(v) for v in parsed]
    except Exception:
        pass
    return None


def _fig_hora_pico(df_todas_zonas, fecha_max=None, dias=7, primary_color: str = _C_PRIMARY):
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
        fmin_act, _, fmin_ant, fmax_ant = _date_windows(fecha_max, dias)
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
    colors = [_rgba(primary_color, 0.18 + 0.72 * v / max_v) for v in avg_act]
    texts = [f"<b>{int(v)}</b>" if i == peak_h else "" for i, v in enumerate(avg_act)]

    fig = go.Figure()
    if avg_ant and sum(avg_ant) > 0:
        fig.add_trace(
            go.Scatter(
                x=horas,
                y=avg_ant,
                mode="lines",
                line=dict(color=_rgba(primary_color, 0.28), width=1.5, dash="dot"),
                fill="tozeroy",
                fillcolor=_rgba(primary_color, 0.04),
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


# ── New visitor ratio ─────────────────────────────────────────────────────────


def _fig_nuevos_ratio(df_todas_zonas, fecha_max, dias=7, primary_color: str = _C_PRIMARY):
    """% de visitantes nuevos — período actual con referencia del período anterior."""
    if (
        "new_visitors" not in df_todas_zonas.columns
        or "unique_visitors" not in df_todas_zonas.columns
    ):
        return None

    fmin_act, _, fmin_ant, fmax_ant = _date_windows(fecha_max, dias)

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
            line_color=_rgba(primary_color, 0.30),
            annotation_text=f"Ant. {media_ant:.0f}%",
            annotation_position="bottom right",
            annotation_font=dict(size=10, color=_rgba(primary_color, 0.55)),
        )
    fig.add_trace(
        go.Scatter(
            x=pd_act["fecha_dt"],
            y=pd_act["pct"],
            mode="lines+markers",
            fill="tozeroy",
            fillcolor=_rgba(primary_color, 0.07),
            line=dict(color=primary_color, width=2),
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


# ── Weekly breakdown (month view) ─────────────────────────────────────────────


def _fig_semanas_mes(df, fecha_max, primary_color: str = _C_PRIMARY):
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
    colors_act = [_rgba(primary_color, op) for op in opacities]
    max_v = max(max(vals_act) if vals_act else 0, max(vals_ant) if vals_ant else 0) or 1

    fig = go.Figure()
    if any(v > 0 for v in vals_ant):
        fig.add_trace(
            go.Bar(
                x=labels,
                y=vals_ant,
                marker=dict(
                    color=_rgba(primary_color, 0.14),
                    line=dict(color=_rgba(primary_color, 0.35), width=1),
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


# ── Temperature vs traffic ────────────────────────────────────────────────────


def _fig_temperatura_trafico(
    df, clima: dict, fecha_max, dias: int = 7, primary_color: str = _C_PRIMARY
):
    """Visitantes (barras, eje izq.) + temperatura máx (línea, eje der.). Actual vs anterior."""
    if not clima:
        return None
    fmin_act, _, fmin_ant, fmax_ant = _date_windows(fecha_max, dias)
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
                color=_rgba(primary_color, 0.16),
                line=dict(color=_rgba(primary_color, 0.32), width=1),
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
            marker=dict(color=_rgba(primary_color, 0.78), cornerradius=5),
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


# ── Rain vs traffic ───────────────────────────────────────────────────────────


def _fig_lluvia_trafico(df, clima: dict, fecha_max, dias: int = 7, primary_color: str = _C_PRIMARY):
    """Visitantes (barras sólidas/translúcidas) + precipitación (área, eje der.). Actual vs anterior."""
    if not clima:
        return None
    fmin_act, _, fmin_ant, fmax_ant = _date_windows(fecha_max, dias)
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
                color=_rgba(primary_color, 0.16),
                line=dict(color=_rgba(primary_color, 0.32), width=1),
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
            marker=dict(color=_rgba(primary_color, 0.78), cornerradius=5),
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
