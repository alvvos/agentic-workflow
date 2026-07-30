"""
Generador de informes PDF.
Flujo: datos DB → Plotly figs → PNG vía Kaleido → Jinja2 → WeasyPrint PDF.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"

_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
_MESES_LARGO = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
_DIAS_ES = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]

_C_RED = "#E60012"
_C_DARK = "#1a1a1a"
_C_MUTED = "#aaa"

_PALETTE = ["#E60012", "#1a1a1a", "#D35400", "#6C3483", "#148F77", "#2980B9", "#8E44AD", "#4D4D4D"]


# ── Date helpers ──────────────────────────────────────────────────────────────


def _short(d) -> str:
    """'20 jul 2026'"""
    if isinstance(d, str):
        d = pd.to_datetime(d)
    return f"{d.day} {_MESES[d.month-1]} {d.year}"


def _short_range(d0, d1) -> str:
    """'20–26 jul 2026' or '20 jul – 3 ago 2026'"""
    d0, d1 = pd.to_datetime(d0), pd.to_datetime(d1)
    if d0.month == d1.month:
        return f"{d0.day}–{d1.day} {_MESES[d1.month-1]} {d1.year}"
    return f"{d0.day} {_MESES[d0.month-1]} – {d1.day} {_MESES[d1.month-1]} {d1.year}"


def _long_range(d0, d1) -> str:
    """'Del 20 de julio al 26 de julio de 2026'"""
    d0, d1 = pd.to_datetime(d0), pd.to_datetime(d1)
    return f"Del {d0.day} de {_MESES_LARGO[d0.month-1]} al {d1.day} de {_MESES_LARGO[d1.month-1]} de {d1.year}"


def _period_label(date_from: str, date_to: str, period: str) -> tuple[str, str, str, str]:
    """Returns (short_current, short_prev, full_current, full_prev)."""
    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    p0, p1 = d0 - timedelta(days=dias), d0 - timedelta(days=1)
    return (
        _short_range(d0, d1),
        _short_range(p0, p1),
        _long_range(d0, d1),
        _long_range(p0, p1),
    )


# ── Chart utilities ───────────────────────────────────────────────────────────


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _fig_to_b64(fig: go.Figure, width: int = 900, height: int = 300) -> str:
    img = fig.to_image(format="png", width=width, height=height, scale=2)
    return base64.b64encode(img).decode()


_FONT = dict(family="Helvetica Neue, Helvetica, Arial, sans-serif", size=13, color="#333")


def _base(height: int = 300) -> dict:
    return dict(
        height=height,
        margin=dict(t=14, b=44, l=56, r=14),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=_FONT,
        showlegend=True,
        legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
    )


# ── External data helpers ─────────────────────────────────────────────────────


def _fetch_weather(loc_uuid: str, d0: pd.Timestamp, d1: pd.Timestamp) -> pd.DataFrame:
    try:
        from src.db.queries import _get_weather

        raw = _get_weather(loc_uuid, pd.date_range(d0, d1, freq="D"))
        if raw.empty:
            return pd.DataFrame()
        raw["fecha"] = pd.to_datetime(raw["fecha"])
        return raw[(raw["fecha"] >= d0) & (raw["fecha"] <= d1)].reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _get_cruceros(loc_uuid: str, d0: pd.Timestamp, d1: pd.Timestamp) -> pd.Series:
    try:
        from src.db.queries import get_señal_diaria

        s = get_señal_diaria(loc_uuid, "n_pasajeros_crucero_dia", d0, d1)
        if s.sum() == 0:
            s = get_señal_diaria(loc_uuid, "n_pasajeros_crucero_oficial", d0, d1)
        return s
    except Exception:
        return pd.Series(0.0, index=pd.date_range(d0, d1, freq="D"), name="cruceros")


# ── Chart 1: Tráfico — diario/semanal/mensual según rango ───────────────────


def _chart_trafico(
    df_v: pd.DataFrame, zonas_info: list[dict], date_from: str, date_to: str
) -> go.Figure:
    from plotly.subplots import make_subplots

    if df_v.empty:
        return go.Figure()

    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    df = df_v[(df_v["fecha"] >= d0) & (df_v["fecha"] <= d1)].copy()

    # Granularidad según rango
    if dias > 90:
        resample_freq = "MS"

        def _label(d):
            return f"{_MESES[d.month-1]} {d.year}"

        use_bars = True
    elif dias > 21:
        resample_freq = "W-MON"

        def _label(d):
            return f"{d.day} {_MESES[d.month-1]}"

        use_bars = True
    else:
        resample_freq = None

        def _label(d):
            return f"{_DIAS_ES[d.dayofweek]} {d.day}/{d.month}"

        use_bars = False

    def _agg(zone_id: str) -> pd.DataFrame:
        sub = df[df["zona_id"] == zone_id].copy()
        if resample_freq:
            sub = (
                sub.set_index("fecha")["unique_visitors"]
                .resample(resample_freq)
                .sum()
                .reset_index()
                .rename(columns={"fecha": "fecha"})
            )
            sub = sub[sub["fecha"] >= d0].reset_index(drop=True)
        else:
            sub = (
                sub.groupby("fecha")["unique_visitors"]
                .sum()
                .reset_index()
                .sort_values("fecha")
                .reset_index(drop=True)
            )
        sub["xl"] = [_label(d) for d in sub["fecha"]]
        return sub

    top_zones = _select_chart_zones(zonas_info)
    ext_zones = [z for z in top_zones if _is_exterior(z)]
    int_zones = [z for z in top_zones if not _is_exterior(z)]
    if not ext_zones or not int_zones:
        ext_zones, int_zones = top_zones, []

    rows = 2 if int_zones else 1
    row_heights = [0.40, 0.60] if rows == 2 else [1.0]
    subplot_titles = ["Zona exterior", "Zonas interiores"] if rows == 2 else [""]

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        vertical_spacing=0.12,
        subplot_titles=subplot_titles,
    )

    peak_lbl, peak_val = None, 0

    for idx, z in enumerate(ext_zones):
        dz = _agg(z["zona_id"])
        if dz.empty:
            continue
        color = _PALETTE[idx % len(_PALETTE)]
        if use_bars:
            fig.add_trace(
                go.Bar(
                    x=dz["xl"],
                    y=dz["unique_visitors"],
                    name=z["nombre"],
                    marker_color=color,
                    opacity=0.85,
                ),
                row=1,
                col=1,
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=dz["xl"],
                    y=dz["unique_visitors"],
                    mode="lines+markers",
                    name=z["nombre"],
                    line=dict(color=color, width=2.5),
                    marker=dict(color=color, size=6, line=dict(color="white", width=1.5)),
                ),
                row=1,
                col=1,
            )
        loc_max = dz["unique_visitors"].max()
        if loc_max > peak_val:
            peak_lbl = dz.loc[dz["unique_visitors"].idxmax(), "xl"]
            peak_val = loc_max

    if peak_lbl and not use_bars:
        fig.add_annotation(
            row=1,
            col=1,
            x=peak_lbl,
            y=peak_val,
            text=f"Pico: {int(peak_val):,}",
            showarrow=True,
            arrowhead=2,
            arrowsize=0.8,
            arrowcolor="#888",
            ax=0,
            ay=-26,
            font=dict(size=10, color="#555"),
            bgcolor="rgba(255,255,255,0.88)",
        )

    for idx, z in enumerate(int_zones):
        dz = _agg(z["zona_id"])
        if dz.empty:
            continue
        color = _PALETTE[(len(ext_zones) + idx) % len(_PALETTE)]
        row = 2 if rows == 2 else 1
        if use_bars:
            fig.add_trace(
                go.Bar(
                    x=dz["xl"],
                    y=dz["unique_visitors"],
                    name=z["nombre"],
                    marker_color=color,
                    opacity=0.85,
                ),
                row=row,
                col=1,
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=dz["xl"],
                    y=dz["unique_visitors"],
                    mode="lines+markers",
                    name=z["nombre"],
                    line=dict(color=color, width=2.5),
                    marker=dict(color=color, size=6, line=dict(color="white", width=1.5)),
                ),
                row=row,
                col=1,
            )

    fig.update_layout(
        height=290,
        barmode="group",
        margin=dict(t=26, b=42, l=60, r=14),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=_FONT,
        showlegend=True,
        legend=dict(orientation="h", y=-0.12, x=0, font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=False, tickfont=dict(size=11), showline=True, linecolor="#e8e8e8")
    fig.update_yaxes(showgrid=True, gridcolor="#f4f4f4", zeroline=False, tickfont=dict(size=11))
    for ann in fig.layout.annotations:
        ann.font.size = 11
        ann.font.color = "#888"

    return fig


# ── Chart 2: Distribución por día de semana — actual vs anterior ──────────────


def _chart_dias_vs_prev(df_v: pd.DataFrame, date_from: str, date_to: str, dias: int) -> go.Figure:
    fig = go.Figure()
    if df_v.empty:
        return fig

    d0 = pd.to_datetime(date_from)
    d1 = pd.to_datetime(date_to)
    p1 = d0 - timedelta(days=1)
    p0 = d0 - timedelta(days=dias)

    def _dow_avg(fmin, fmax):
        mask = (df_v["fecha"] >= fmin) & (df_v["fecha"] <= fmax)
        sub = df_v[mask].copy()
        if sub.empty:
            return pd.Series(0, index=range(7))
        sub["dow"] = sub["fecha"].dt.dayofweek
        return (
            sub.groupby(["fecha", "dow"])["unique_visitors"]
            .sum()
            .reset_index()
            .groupby("dow")["unique_visitors"]
            .mean()
            .reindex(range(7), fill_value=0)
        )

    act = _dow_avg(d0, d1)
    ant = _dow_avg(p0, p1)

    # Period labels for legend
    lbl_act = _short_range(d0, d1)
    lbl_ant = _short_range(p0, p1)

    fig.add_trace(
        go.Bar(
            name=lbl_ant,
            x=_DIAS_ES,
            y=ant.values.round().astype(int),
            marker_color=_rgba(_C_RED, 0.2),
            marker_line=dict(color=_rgba(_C_RED, 0.4), width=1),
            hovertemplate=f"<b>{lbl_ant}</b><br>%{{x}}: %{{y:,}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name=lbl_act,
            x=_DIAS_ES,
            y=act.values.round().astype(int),
            marker_color=_C_RED,
            text=[f"{int(v):,}" if v > 0 else "" for v in act.values],
            textposition="outside",
            textfont=dict(size=10, color="#555"),
            hovertemplate=f"<b>{lbl_act}</b><br>%{{x}}: %{{y:,}}<extra></extra>",
            cliponaxis=False,
        )
    )

    layout = _base(220)
    layout["margin"] = dict(t=18, b=54, l=60, r=14)
    layout["legend"] = dict(
        orientation="h", y=-0.28, x=0, font=dict(size=11), bgcolor="rgba(0,0,0,0)"
    )
    fig.update_layout(
        **layout,
        barmode="group",
        bargap=0.22,
        bargroupgap=0.04,
        xaxis=dict(showgrid=False, tickfont=dict(size=11)),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", zeroline=False, tickfont=dict(size=11)),
    )
    return fig


# ── Chart 3: Embudo (solo un paso por nivel) ──────────────────────────────────


def _chart_embudo(zonas_info: list[dict], df_v: pd.DataFrame, date_from: str, date_to: str):
    if df_v.empty:
        return None

    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    df = df_v[(df_v["fecha"] >= d0) & (df_v["fecha"] <= d1)]
    zone_totals = df.groupby("zona_id")["unique_visitors"].sum().to_dict()

    _ROLES = {
        "exterior": 0,
        "entry_zone": 0,
        "calle": 0,
        "tienda": 1,
        "interior": 1,
        "caja": 2,
        "checkout": 2,
        "end_zone": 2,
    }

    funnel: dict[int, tuple[str, int]] = {}
    for z in zonas_info:
        tipo = (z.get("tipo_zona") or "").lower()
        nombre_l = z["nombre"].lower()
        rank = _ROLES.get(tipo)
        if rank is None:
            for kw, r in _ROLES.items():
                if kw in nombre_l:
                    rank = r
                    break
        if rank is None:
            continue
        v = int(zone_totals.get(z["zona_id"], 0))
        if rank not in funnel or v > funnel[rank][1]:
            funnel[rank] = (z["nombre"], v)

    steps = sorted(funnel.items())
    if len(steps) < 2:
        return None

    labels = [s[1][0] for s in steps]
    values = [s[1][1] for s in steps]

    # Barras horizontales independientes — cada zona tiene escala propia para que
    # todas sean visibles aunque los ratios de conversión sean muy bajos.
    colors = [_rgba(_C_RED, 1.0 - 0.28 * i) for i in range(len(labels))]

    fig = go.Figure()
    for i, (label, value) in enumerate(zip(labels, values)):
        pct_ref = value / values[0] * 100 if values[0] else 0
        pct_prev = value / values[i - 1] * 100 if i > 0 and values[i - 1] else 100.0
        label_prev = f"{pct_prev:.1f}% del paso anterior" if i > 0 else "100% referencia"
        fig.add_trace(
            go.Bar(
                y=[label],
                x=[value],
                orientation="h",
                marker_color=colors[i],
                text=f"  {value:,}   ({pct_ref:.1f}% del total exterior · {label_prev})",
                textposition="outside",
                textfont=dict(size=10, color="#444"),
                cliponaxis=False,
            )
        )

    n = len(labels)
    fig.update_layout(
        height=max(160, 60 * n + 40),
        barmode="overlay",
        showlegend=False,
        margin=dict(t=8, b=8, l=70, r=14),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=_FONT,
        xaxis=dict(
            showgrid=False, showticklabels=False, zeroline=False, range=[0, values[0] * 1.55]
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=12, color="#333"),
            categoryorder="array",
            categoryarray=labels[::-1],
        ),
    )
    return fig


# ── Chart 4: Temperatura ─────────────────────────────────────────────────────


def _chart_temperatura(df_w: pd.DataFrame, date_from: str, date_to: str) -> go.Figure | None:
    if df_w.empty or "temp_max" not in df_w.columns or "temp_min" not in df_w.columns:
        return None
    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    df = df_w[(df_w["fecha"] >= d0) & (df_w["fecha"] <= d1)].copy().sort_values("fecha")
    if df.empty:
        return None

    if dias > 90:
        df["period"] = df["fecha"].dt.to_period("M")
        dg = (
            df.groupby("period")
            .agg(temp_max=("temp_max", "max"), temp_min=("temp_min", "min"))
            .reset_index()
        )
        dg["fecha"] = dg["period"].dt.to_timestamp()
        xl = [f"{_MESES[d.month-1]} {d.year}" for d in dg["fecha"]]
    elif dias > 21:
        df2 = df.set_index("fecha")
        mx = df2["temp_max"].resample("W-MON").max().reset_index()
        mn = df2["temp_min"].resample("W-MON").min().reset_index()
        dg = mx.merge(mn, on="fecha")
        dg = dg[dg["fecha"] >= d0].reset_index(drop=True)
        xl = [f"{d.day} {_MESES[d.month-1]}" for d in dg["fecha"]]
    else:
        dg = df.reset_index(drop=True)
        xl = [f"{_DIAS_ES[d.dayofweek]} {d.day}/{d.month}" for d in dg["fecha"]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xl + xl[::-1],
            y=list(dg["temp_max"].ffill().bfill()) + list(dg["temp_min"].ffill().bfill())[::-1],
            fill="toself",
            fillcolor="rgba(230,0,18,0.07)",
            line=dict(color="rgba(0,0,0,0)"),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xl,
            y=dg["temp_max"],
            mode="lines+markers",
            name="Temp. máx.",
            line=dict(color="#E60012", width=2),
            marker=dict(size=5, color="#E60012"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xl,
            y=dg["temp_min"],
            mode="lines+markers",
            name="Temp. mín.",
            line=dict(color="#2980B9", width=2),
            marker=dict(size=5, color="#2980B9"),
        )
    )
    if "llueve" in df.columns and dias <= 21:
        rain = df[df["llueve"] == 1]
        if not rain.empty:
            rain_xl = [f"{_DIAS_ES[d.dayofweek]} {d.day}/{d.month}" for d in rain["fecha"]]
            fig.add_trace(
                go.Scatter(
                    x=rain_xl,
                    y=rain["temp_max"],
                    mode="markers",
                    name="Lluvia",
                    marker=dict(symbol="circle-open", size=10, color="#2980B9", line=dict(width=2)),
                )
            )

    layout = _base(180)
    layout["margin"] = dict(t=14, b=44, l=48, r=14)
    layout["legend"] = dict(orientation="h", y=-0.30, x=0, font=dict(size=11))
    layout["yaxis"] = dict(title="°C", tickfont=dict(size=11), gridcolor="#f4f4f4", zeroline=False)
    layout["xaxis"] = dict(showgrid=False, tickfont=dict(size=10))
    fig.update_layout(**layout)
    return fig


def _chart_cruceros(s_cruceros: pd.Series, date_from: str, date_to: str) -> go.Figure | None:
    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    dias_rng = pd.date_range(d0, d1, freq="D")
    s = s_cruceros.reindex(dias_rng, fill_value=0)
    if s.sum() == 0:
        return None

    if dias > 90:
        s_agg = s.resample("MS").sum()
        xl = [f"{_MESES[d.month-1]} {d.year}" for d in s_agg.index]
        y = list(s_agg.values)
    elif dias > 21:
        s_agg = s.resample("W-MON").sum()
        s_agg = s_agg[s_agg.index >= d0]
        xl = [f"{d.day} {_MESES[d.month-1]}" for d in s_agg.index]
        y = list(s_agg.values)
    else:
        xl = [f"{_DIAS_ES[d.dayofweek]} {d.day}/{d.month}" for d in dias_rng]
        y = list(s.values)

    fig = go.Figure(
        go.Bar(
            x=xl,
            y=y,
            marker_color=_rgba("#D35400", 0.72),
            name="Pax crucero",
            text=[f"{int(v):,}" if v > 0 else "" for v in y],
            textposition="outside",
            textfont=dict(size=9, color="#555"),
        )
    )
    layout = _base(180)
    layout["margin"] = dict(t=14, b=44, l=60, r=14)
    layout["showlegend"] = False
    layout["yaxis"] = dict(
        showgrid=True,
        gridcolor="#f4f4f4",
        zeroline=False,
        tickfont=dict(size=11),
        title="Pasajeros",
    )
    layout["xaxis"] = dict(showgrid=False, tickfont=dict(size=10))
    fig.update_layout(**layout)
    return fig


def _chart_cruceros_mes(
    s_cruc: pd.Series, d0_mes: pd.Timestamp, d1_mes: pd.Timestamp
) -> go.Figure | None:
    dias_mes = pd.date_range(d0_mes, d1_mes, freq="D")
    s = s_cruc.reindex(dias_mes, fill_value=0)
    if s.sum() == 0:
        return None
    xl = [f"{_DIAS_ES[d.dayofweek]} {d.day}" for d in dias_mes]
    fig = go.Figure(
        go.Bar(
            x=xl,
            y=list(s.values),
            marker_color=_rgba("#D35400", 0.70),
            text=[f"{int(v):,}" if v > 500 else "" for v in s.values],
            textposition="outside",
            textfont=dict(size=8, color="#555"),
        )
    )
    layout = _base(140)
    layout["margin"] = dict(t=8, b=36, l=60, r=14)
    layout["showlegend"] = False
    layout["yaxis"] = dict(
        showgrid=True, gridcolor="#f4f4f4", zeroline=False, tickfont=dict(size=10), title="Pax"
    )
    layout["xaxis"] = dict(showgrid=False, tickfont=dict(size=9))
    fig.update_layout(**layout)
    return fig


def _chart_trafico_diario_mes(
    df_v: pd.DataFrame, zonas_info: list[dict], d0_mes: pd.Timestamp, d1_mes: pd.Timestamp
) -> go.Figure:
    from plotly.subplots import make_subplots

    df = df_v[(df_v["fecha"] >= d0_mes) & (df_v["fecha"] <= d1_mes)].copy()
    if df.empty:
        return go.Figure()
    dias_mes = pd.date_range(d0_mes, d1_mes, freq="D")
    xl = [f"{_DIAS_ES[d.dayofweek]} {d.day}" for d in dias_mes]
    top_zones = _select_chart_zones(zonas_info)
    ext_zones = [z for z in top_zones if _is_exterior(z)]
    int_zones = [z for z in top_zones if not _is_exterior(z)]
    if not ext_zones or not int_zones:
        ext_zones, int_zones = top_zones, []
    rows = 2 if int_zones else 1
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.40, 0.60] if rows == 2 else [1.0],
        vertical_spacing=0.12,
        subplot_titles=["Zona exterior", "Zonas interiores"] if rows == 2 else [""],
    )
    for idx, z in enumerate(ext_zones):
        sub = df[df["zona_id"] == z["zona_id"]].groupby("fecha")["unique_visitors"].sum()
        sub = sub.reindex(dias_mes, fill_value=0)
        fig.add_trace(
            go.Bar(
                x=xl,
                y=list(sub.values),
                name=z["nombre"],
                marker_color=_PALETTE[idx % len(_PALETTE)],
                opacity=0.85,
            ),
            row=1,
            col=1,
        )
    for idx, z in enumerate(int_zones):
        sub = df[df["zona_id"] == z["zona_id"]].groupby("fecha")["unique_visitors"].sum()
        sub = sub.reindex(dias_mes, fill_value=0)
        row = 2 if rows == 2 else 1
        fig.add_trace(
            go.Bar(
                x=xl,
                y=list(sub.values),
                name=z["nombre"],
                marker_color=_PALETTE[(len(ext_zones) + idx) % len(_PALETTE)],
                opacity=0.85,
            ),
            row=row,
            col=1,
        )
    fig.update_layout(
        height=260,
        barmode="group",
        margin=dict(t=26, b=40, l=60, r=14),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=_FONT,
        showlegend=True,
        legend=dict(orientation="h", y=-0.14, x=0, font=dict(size=11)),
    )
    fig.update_xaxes(showgrid=False, tickfont=dict(size=10), showline=True, linecolor="#e8e8e8")
    fig.update_yaxes(showgrid=True, gridcolor="#f4f4f4", zeroline=False, tickfont=dict(size=11))
    for ann in fig.layout.annotations:
        ann.font.size = 11
        ann.font.color = "#888"
    return fig


# ── KPIs & tabla ─────────────────────────────────────────────────────────────


def _delta_fmt(pct: float) -> tuple[str, str, str]:
    """Returns (delta_str, delta_short, delta_class)."""
    if abs(pct) < 1:
        return "Sin cambios", "—", "d-neu"
    sign = "+" if pct > 0 else "-"
    cls = "d-pos" if pct > 0 else "d-neg"
    return f"{sign}{abs(pct):.0f}% vs. período anterior", f"{sign}{abs(pct):.0f}%", cls


def _kpi_fmt(v: float, unit: str = "", dec: int = 0) -> str:
    if v is None:
        return "N/D"
    return f"{v:.{dec}f}{unit}" if dec else f"{int(round(v)):,}{unit}"


def _dwell_min(df: pd.DataFrame) -> float | None:
    """Mean dwell time in minutes. Raw column is in seconds despite _min suffix."""
    if "dwell_time" not in df.columns:
        return None
    v = df["dwell_time"].dropna()
    return float(v.mean() / 60) if not v.empty else None


def _build_kpis(df_v: pd.DataFrame, date_from: str, date_to: str) -> list[dict]:
    if df_v.empty:
        return []
    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    p1 = d0 - timedelta(days=1)
    p0 = d0 - timedelta(days=dias)

    act = df_v[(df_v["fecha"] >= d0) & (df_v["fecha"] <= d1)]
    ant = df_v[(df_v["fecha"] >= p0) & (df_v["fecha"] <= p1)]

    vis_act = int(act["unique_visitors"].sum())
    vis_ant = int(ant["unique_visitors"].sum())
    delta_vis = (vis_act - vis_ant) / vis_ant * 100 if vis_ant else 0

    dias_act = act[act["unique_visitors"] > 0]["fecha"].nunique()

    dw_act = _dwell_min(act)
    dw_ant = _dwell_min(ant)
    delta_dw = (dw_act - dw_ant) / dw_ant * 100 if dw_ant and dw_act else 0

    dv_str, _, dv_cls = _delta_fmt(delta_vis)
    ddw_str, _, ddw_cls = _delta_fmt(delta_dw)

    return [
        {
            "label": "Visitas totales",
            "value": _kpi_fmt(vis_act),
            "delta": dv_str,
            "delta_class": dv_cls,
            "ref": f"{_kpi_fmt(vis_ant)} período anterior",
        },
        {
            "label": "Días comerciales",
            "value": str(dias_act),
            "delta": f"de {dias} en el período",
            "delta_class": "d-neu",
            "ref": None,
        },
        {
            "label": "Visitas / día activo",
            "value": _kpi_fmt(vis_act / dias_act) if dias_act else "—",
            "delta": dv_str,
            "delta_class": dv_cls,
            "ref": None,
        },
        {
            "label": "Estancia media",
            "value": _kpi_fmt(dw_act, " min", 1) if dw_act else "N/D",
            "delta": ddw_str if dw_act else "Sin datos",
            "delta_class": ddw_cls if dw_act else "d-neu",
            "ref": f"{_kpi_fmt(dw_ant, ' min', 1)} anterior" if dw_ant else None,
        },
    ]


def _build_zonas_tabla(
    df_v: pd.DataFrame, zonas_info: list[dict], date_from: str, date_to: str
) -> list[dict]:
    rows = []
    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    p1 = d0 - timedelta(days=1)
    p0 = d0 - timedelta(days=dias)

    for idx, z in enumerate(zonas_info):
        zid = z["zona_id"]
        color = _PALETTE[idx % len(_PALETTE)]
        act = df_v[(df_v["zona_id"] == zid) & (df_v["fecha"] >= d0) & (df_v["fecha"] <= d1)]
        ant = df_v[(df_v["zona_id"] == zid) & (df_v["fecha"] >= p0) & (df_v["fecha"] <= p1)]

        vis_act = int(act["unique_visitors"].sum())
        vis_ant = int(ant["unique_visitors"].sum())
        pct = (vis_act - vis_ant) / vis_ant * 100 if vis_ant else 0
        _, delta_short, delta_cls = _delta_fmt(pct)

        dias_act = act[act["unique_visitors"] > 0]["fecha"].nunique()
        vis_dia = round(vis_act / dias_act) if dias_act else 0

        dw = _dwell_min(act) if not act.empty else None

        rows.append(
            {
                "nombre": z["nombre"],
                "color": color,
                "visitas": f"{vis_act:,}",
                "delta_short": delta_short,
                "delta_class": delta_cls,
                "visitas_dia": f"{vis_dia:,}",
                "estancia": f"{dw:.1f} min" if dw else "—",
                "dias_activos": str(dias_act),
            }
        )
    return rows


_EXT_KW = {"exterior", "entry_zone", "calle"}
_CAJA_KW = {"caja", "checkout", "end_zone"}


def _is_exterior(z: dict) -> bool:
    tipo = (z.get("tipo_zona") or "").lower()
    if tipo in _EXT_KW:
        return True
    return any(kw in z["nombre"].lower() for kw in ("calle", "exterior"))


def _is_caja(z: dict) -> bool:
    tipo = (z.get("tipo_zona") or "").lower()
    return tipo in _CAJA_KW or "caja" in z["nombre"].lower()


def _select_chart_zones(zonas_info: list[dict]) -> list[dict]:
    """Top-level zones + any checkout/caja sub-zones (which carry their own funnel step)."""
    tops = [z for z in zonas_info if not z.get("parent_zona_id")]
    if not tops:
        tops = list(zonas_info[:6])
    seen = {z["zona_id"] for z in tops}
    for z in zonas_info:
        if z.get("parent_zona_id") and z["zona_id"] not in seen and _is_caja(z):
            tops.append(z)
            seen.add(z["zona_id"])
    return tops[:8]


def _pct_text(pct: float) -> str:
    """Natural language for a percentage change — no arrows or symbols."""
    if abs(pct) < 1:
        return "sin variación significativa"
    dir_ = "subida" if pct > 0 else "caída"
    return f"{dir_} del {abs(pct):.0f}%"


def _build_insights(
    df_v: pd.DataFrame,
    zonas_info: list[dict],
    date_from: str,
    date_to: str,
    loc_uuid: str = "",
    df_weather_preloaded: pd.DataFrame | None = None,
    s_cruceros: pd.Series | None = None,
) -> list[dict]:
    items = []
    if df_v.empty:
        return items

    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    dias = (d1 - d0).days + 1
    p1 = d0 - timedelta(days=1)
    p0 = d0 - timedelta(days=dias)

    act = df_v[(df_v["fecha"] >= d0) & (df_v["fecha"] <= d1)]
    ant = df_v[(df_v["fecha"] >= p0) & (df_v["fecha"] <= p1)]

    top_zones = _select_chart_zones(zonas_info)
    ext_zones = [z for z in top_zones if _is_exterior(z)]
    int_zones = [z for z in top_zones if not _is_exterior(z)]

    def _zone_visits(z, df):
        return int(df[df["zona_id"] == z["zona_id"]]["unique_visitors"].sum())

    def _zone_dwell_min(z, df):
        return _dwell_min(df[df["zona_id"] == z["zona_id"]])

    # Weather
    df_weather = pd.DataFrame()
    if df_weather_preloaded is not None and not df_weather_preloaded.empty:
        df_weather = df_weather_preloaded[
            (df_weather_preloaded["fecha"] >= d0) & (df_weather_preloaded["fecha"] <= d1)
        ].copy()
    elif loc_uuid:
        try:
            from src.db.queries import _get_weather

            raw_w = _get_weather(loc_uuid, act["fecha"].drop_duplicates())
            if not raw_w.empty:
                raw_w["fecha"] = pd.to_datetime(raw_w["fecha"])
                df_weather = raw_w[(raw_w["fecha"] >= d0) & (raw_w["fecha"] <= d1)].copy()
        except Exception:
            pass

    def _pct_connector(dg: float, singular="más", plural_neg="menos") -> str:
        """'un 4.7% más' / 'un 4.7% menos'"""
        word = singular if dg >= 0 else plural_neg
        return f"un {abs(dg):.1f}% {word}"

    # ── 1. Tráfico exterior: actual vs anterior ───────────────────────────────
    if ext_zones:
        ez = ext_zones[0]
        ext_act = _zone_visits(ez, act)
        ext_ant = _zone_visits(ez, ant)
        if ext_act and ext_ant:
            dg = (ext_act - ext_ant) / ext_ant * 100
            nivel = (
                "success"
                if dg >= 5
                else ("danger" if dg <= -10 else ("warning" if dg < -5 else "secondary"))
            )
            items.append(
                {
                    "level": nivel,
                    "text": f"Tráfico exterior «{ez['nombre']}»: pasó de {ext_ant:,} a {ext_act:,} visitas, "
                    f"{_pct_connector(dg)} que en el período anterior.",
                }
            )

    # ── 2. Tasa de conversión exterior a interior ─────────────────────────────
    if ext_zones and int_zones:
        iz = max(int_zones, key=lambda z: _zone_visits(z, act))
        ext_act = _zone_visits(ext_zones[0], act)
        int_act = _zone_visits(iz, act)
        ext_ant = _zone_visits(ext_zones[0], ant)
        int_ant = _zone_visits(iz, ant)
        if ext_act and int_act:
            conv_act = int_act / ext_act * 100
            if ext_ant and int_ant:
                conv_ant = int_ant / ext_ant * 100
                dg_conv = conv_act - conv_ant
                dir_pp = "ganando" if dg_conv >= 0 else "perdiendo"
                items.append(
                    {
                        "level": "primary",
                        "text": f"Tasa de conversión de «{ext_zones[0]['nombre']}» a «{iz['nombre']}»: "
                        f"pasó del {conv_ant:.1f}% al {conv_act:.1f}%, "
                        f"{dir_pp} {abs(dg_conv):.1f} puntos porcentuales respecto al período anterior.",
                    }
                )
            else:
                items.append(
                    {
                        "level": "primary",
                        "text": f"Tasa de conversión de «{ext_zones[0]['nombre']}» a «{iz['nombre']}»: {conv_act:.1f}%.",
                    }
                )

    # ── 3. Jornada de mayor afluencia ─────────────────────────────────────────
    agg = act.groupby("fecha")["unique_visitors"].sum()
    if not agg.empty:
        pk_d = agg.idxmax()
        pk_v = int(agg.max())
        media_dia = float(agg.mean())
        exceso = (pk_v - media_dia) / media_dia * 100 if media_dia else 0
        items.append(
            {
                "level": "primary",
                "text": f"La jornada de mayor afluencia fue el {_DIAS_ES[pk_d.dayofweek]} {_short(pk_d)}, "
                f"con {pk_v:,} visitas, {abs(exceso):.0f}% por encima de la media diaria del período ({int(media_dia):,} visitas por día).",
            }
        )

    # ── 4. Estancia media: actual vs anterior ─────────────────────────────────
    if int_zones:
        dwell_data = [(z, _zone_dwell_min(z, act)) for z in int_zones]
        dwell_data = [(z, v) for z, v in dwell_data if v and v > 0]
        if dwell_data:
            best_dw_z, best_dw = max(dwell_data, key=lambda x: x[1])
            prev_dw = _zone_dwell_min(best_dw_z, ant)
            if prev_dw:
                dg_dw = (best_dw - prev_dw) / prev_dw * 100
                items.append(
                    {
                        "level": "secondary",
                        "text": f"Estancia media en «{best_dw_z['nombre']}»: pasó de {prev_dw:.1f} a {best_dw:.1f} minutos, "
                        f"{_pct_connector(dg_dw)} que en el período anterior.",
                    }
                )
            else:
                items.append(
                    {
                        "level": "secondary",
                        "text": f"Estancia media en «{best_dw_z['nombre']}»: {best_dw:.1f} minutos.",
                    }
                )

    # ── 5. Fin de semana vs días laborables ───────────────────────────────────
    act2 = act.copy()
    act2["dow"] = act2["fecha"].dt.dayofweek
    finde = act2[act2["dow"] >= 5]["unique_visitors"].mean()
    laboral = act2[act2["dow"] < 5]["unique_visitors"].mean()
    if finde and laboral and laboral > 0:
        ratio = finde / laboral
        mayor = "fin de semana" if ratio >= 1 else "días laborables"
        menor = "días laborables" if ratio >= 1 else "fin de semana"
        dif_pct = abs(ratio - 1) * 100
        items.append(
            {
                "level": "secondary",
                "text": f"Media de visitas: {int(finde):,} en fin de semana frente a {int(laboral):,} en días laborables. "
                f"El {mayor} concentra {dif_pct:.0f}% más afluencia que el {menor}.",
            }
        )

    # ── 6. Lluvia: comparativa días lluvia vs días secos ──────────────────────
    if not df_weather.empty and "llueve" in df_weather.columns and ext_zones:
        try:
            from scipy.stats import mannwhitneyu

            merged = act.merge(df_weather[["fecha", "llueve"]], on="fecha", how="left")
            ez_id = ext_zones[0]["zona_id"]
            ext_m = (
                merged[merged["zona_id"] == ez_id]
                .groupby(["fecha", "llueve"])["unique_visitors"]
                .sum()
                .reset_index()
            )
            rain_vis = ext_m[ext_m["llueve"] == 1]["unique_visitors"].values
            dry_vis = ext_m[ext_m["llueve"] == 0]["unique_visitors"].values
            n_lluvia = int(df_weather["llueve"].fillna(0).sum())
            if len(rain_vis) >= 2 and len(dry_vis) >= 2:
                _, p = mannwhitneyu(rain_vis, dry_vis, alternative="two-sided")
                concl = (
                    "La diferencia es estadísticamente significativa."
                    if p < 0.05
                    else "La diferencia entre ambos grupos no es estadísticamente significativa."
                )
                items.append(
                    {
                        "level": "warning" if p < 0.05 else "secondary",
                        "text": f"Los {n_lluvia} días de lluvia del período registraron una media de {int(rain_vis.mean()):,} visitas "
                        f"en «{ext_zones[0]['nombre']}» frente a {int(dry_vis.mean()):,} en los días sin precipitación. "
                        f"{concl}",
                    }
                )
            elif n_lluvia > 0:
                items.append(
                    {
                        "level": "secondary",
                        "text": f"Se registraron {n_lluvia} días de lluvia en el período "
                        f"(muestra insuficiente para comparación estadística).",
                    }
                )
        except Exception:
            pass

    # ── 7. Cruceros: volumen y asociación con tráfico exterior ────────────────
    if s_cruceros is not None and ext_zones:
        try:
            from scipy.stats import kendalltau

            dias_rng = pd.date_range(d0, d1, freq="D")
            s_c = s_cruceros.reindex(dias_rng, fill_value=0)
            dias_crucero = int((s_c > 0).sum())
            pax_total = int(s_c.sum())
            ez_id = ext_zones[0]["zona_id"]
            vis_ext = (
                act[act["zona_id"] == ez_id]
                .groupby("fecha")["unique_visitors"]
                .sum()
                .reindex(dias_rng, fill_value=0)
            )
            tau, p = kendalltau(s_c.values, vis_ext.values)
            fuerza = (
                "despreciable"
                if abs(tau) < 0.1
                else "débil" if abs(tau) < 0.3 else "moderada" if abs(tau) < 0.5 else "fuerte"
            )
            dir_tau = "positiva" if tau >= 0 else "negativa"
            pax_media = int(s_c[s_c > 0].mean()) if dias_crucero > 0 else 0
            if p < 0.05:
                concl = (
                    f"El análisis estadístico muestra una asociación {dir_tau} {fuerza} "
                    f"entre el volumen de pasajeros de crucero y el tráfico en «{ext_zones[0]['nombre']}»."
                )
            else:
                concl = (
                    "El análisis estadístico no encuentra asociación significativa "
                    f"entre los cruceros y el tráfico en «{ext_zones[0]['nombre']}» en este período."
                )
            items.append(
                {
                    "level": "primary" if p < 0.05 else "secondary",
                    "text": f"Cruceros en el Puerto de Málaga: {dias_crucero} escalas con {pax_total:,} pasajeros totales "
                    f"(media de {pax_media:,} por escala). {concl}",
                }
            )
        except Exception:
            pass

    return items


# ── Monthly chapter helpers ───────────────────────────────────────────────────


def _build_semanas_mes(
    df_v: pd.DataFrame,
    zonas_info: list[dict],
    df_w_mes: pd.DataFrame | None,
    s_cruc_mes: pd.Series | None,
    d0_mes: pd.Timestamp,
    d1_mes: pd.Timestamp,
) -> list[dict]:
    top_zones = _select_chart_zones(zonas_info)
    ext_zones = [z for z in top_zones if _is_exterior(z)]
    int_zones = [z for z in top_zones if not _is_exterior(z)]

    # Semanas del mes (lunes a domingo, recortadas al mes)
    first_mon = d0_mes - timedelta(days=d0_mes.dayofweek)
    week_starts = pd.date_range(first_mon, d1_mes, freq="W-MON")

    semanas = []
    for ws in week_starts:
        ws_eff = max(ws, d0_mes)
        we_eff = min(ws + timedelta(days=6), d1_mes)
        df_sem = df_v[(df_v["fecha"] >= ws_eff) & (df_v["fecha"] <= we_eff)]
        if df_sem.empty:
            continue
        total_vis = int(df_sem["unique_visitors"].sum())
        agg_d = df_sem.groupby("fecha")["unique_visitors"].sum()
        pico_d = agg_d.idxmax()
        pico_vis = int(agg_d.max())
        media_vis = int(agg_d.mean())

        # Cruceros
        cruc_total, cruc_dias = 0, 0
        if s_cruc_mes is not None:
            sem_idx = pd.date_range(ws_eff, we_eff, freq="D")
            s_c = s_cruc_mes.reindex(sem_idx, fill_value=0)
            cruc_total = int(s_c.sum())
            cruc_dias = int((s_c > 0).sum())

        # Clima
        temp_media, n_lluvia = None, 0
        if df_w_mes is not None and not df_w_mes.empty:
            w_sem = df_w_mes[(df_w_mes["fecha"] >= ws_eff) & (df_w_mes["fecha"] <= we_eff)]
            if not w_sem.empty and "temp_max" in w_sem.columns:
                temp_media = w_sem["temp_max"].dropna().mean()
            if "llueve" in w_sem.columns:
                n_lluvia = int(w_sem["llueve"].fillna(0).sum())

        # Tasa de conversión calle→tienda
        conv_text = ""
        if ext_zones and int_zones:
            ez_v = int(
                df_sem[df_sem["zona_id"] == ext_zones[0]["zona_id"]]["unique_visitors"].sum()
            )
            iz = max(
                int_zones,
                key=lambda z: int(
                    df_sem[df_sem["zona_id"] == z["zona_id"]]["unique_visitors"].sum()
                ),
            )
            iz_v = int(df_sem[df_sem["zona_id"] == iz["zona_id"]]["unique_visitors"].sum())
            if ez_v > 0:
                conv_text = f"Conversión calle a tienda: {iz_v/ez_v*100:.1f}%."

        texto_parts = [
            f"Pico el {_DIAS_ES[pico_d.dayofweek]} {pico_d.day}/{pico_d.month} "
            f"({pico_vis:,} vis., {(pico_vis-media_vis)/media_vis*100:+.0f}% sobre la media de la semana)."
        ]
        if n_lluvia > 0:
            texto_parts.append(f"Días de lluvia: {n_lluvia}.")
        if temp_media:
            texto_parts.append(f"Temp. máx. media: {temp_media:.0f}°C.")
        if cruc_dias > 0:
            texto_parts.append(f"Escalas de crucero: {cruc_dias} ({cruc_total:,} pax).")
        if conv_text:
            texto_parts.append(conv_text)

        semanas.append(
            {
                "label": _short_range(ws_eff, we_eff),
                "visitas": f"{total_vis:,}",
                "texto": " ".join(texto_parts),
                "cruc_dias": cruc_dias,
                "cruc_total": f"{cruc_total:,}" if cruc_total > 0 else "",
                "lluvia": n_lluvia,
                "temp": f"{temp_media:.0f}°C" if temp_media else "",
            }
        )

    return semanas


def _build_capitulos(
    df_v: pd.DataFrame,
    zonas_info: list[dict],
    df_weather: pd.DataFrame,
    s_cruceros: pd.Series,
    date_from: str,
    date_to: str,
) -> list[dict]:
    d0, d1 = pd.to_datetime(date_from), pd.to_datetime(date_to)
    months = pd.period_range(d0.to_period("M"), d1.to_period("M"), freq="M")

    capitulos = []
    for i, mes_period in enumerate(months):
        d0_mes = max(pd.Timestamp(mes_period.start_time), d0)
        d1_mes = min(pd.Timestamp(mes_period.end_time).normalize(), d1)

        mes_label = f"{_MESES_LARGO[d0_mes.month-1]} {d0_mes.year}"

        kpis_mes = _build_kpis(df_v, d0_mes.isoformat()[:10], d1_mes.isoformat()[:10])

        fig_mes = _chart_trafico_diario_mes(df_v, zonas_info, d0_mes, d1_mes)
        chart_mes_b64 = _fig_to_b64(fig_mes, width=900, height=260) if fig_mes.data else ""

        df_w_mes = (
            df_weather[(df_weather["fecha"] >= d0_mes) & (df_weather["fecha"] <= d1_mes)].copy()
            if not df_weather.empty
            else pd.DataFrame()
        )

        s_cruc_mes = (
            s_cruceros[(s_cruceros.index >= d0_mes) & (s_cruceros.index <= d1_mes)]
            if s_cruceros is not None
            else None
        )

        chart_cruc_b64 = ""
        if s_cruc_mes is not None and s_cruc_mes.sum() > 0:
            fig_cruc = _chart_cruceros_mes(s_cruc_mes, d0_mes, d1_mes)
            if fig_cruc:
                chart_cruc_b64 = _fig_to_b64(fig_cruc, width=900, height=140)

        semanas = _build_semanas_mes(
            df_v, zonas_info, df_w_mes if not df_w_mes.empty else None, s_cruc_mes, d0_mes, d1_mes
        )

        insights_mes = _build_insights(
            df_v,
            zonas_info,
            d0_mes.isoformat()[:10],
            d1_mes.isoformat()[:10],
            df_weather_preloaded=df_w_mes if not df_w_mes.empty else None,
            s_cruceros=s_cruc_mes if (s_cruc_mes is not None and s_cruc_mes.sum() > 0) else None,
        )

        capitulos.append(
            {
                "num": i + 1,
                "total": len(months),
                "mes_label": mes_label,
                "kpis": kpis_mes,
                "chart_b64": chart_mes_b64,
                "chart_cruc_b64": chart_cruc_b64,
                "semanas": semanas,
                "insights": insights_mes,
            }
        )

    return capitulos


# ── Public entry point ────────────────────────────────────────────────────────


def generar_pdf_informe(
    loc_uuid: str,
    period: str,
    date_from: str,
    date_to: str,
    session_id: str = "",
) -> bytes:
    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    from src.core.data_master import mapa_tiendas
    from src.core.org_branding import get_branding_from_locs
    from src.db.queries import get_df_visitas, get_location_by_uuid, get_zones_for_loc

    loc_meta = get_location_by_uuid(loc_uuid) or {}
    loc_nombre = mapa_tiendas.get(loc_uuid, loc_meta.get("name", loc_uuid))
    branding = get_branding_from_locs([loc_uuid])
    ciudad = loc_meta.get("city", "")

    df_v = get_df_visitas(loc_uuid)
    if not df_v.empty:
        df_v["fecha"] = pd.to_datetime(df_v["fecha"])

    zonas_info = [z for z in get_zones_for_loc(loc_uuid) if not z.get("oculta")]
    dias = (pd.to_datetime(date_to) - pd.to_datetime(date_from)).days + 1

    # Logo base64
    logo_b64 = ""
    if branding.logo_asset:
        lp = _ASSETS_DIR / branding.logo_asset.removeprefix("/assets/")
        if lp.exists():
            logo_b64 = base64.b64encode(lp.read_bytes()).decode()

    # Period labels
    period_short, prev_short, period_full, prev_full = _period_label(date_from, date_to, period)

    # External data (weather + cruceros)
    d0_g, d1_g = pd.to_datetime(date_from), pd.to_datetime(date_to)
    df_weather = _fetch_weather(loc_uuid, d0_g, d1_g)
    s_cruceros = _get_cruceros(loc_uuid, d0_g, d1_g)
    tiene_cruceros = bool(s_cruceros.sum() > 0)

    # KPIs & tabla
    kpis = _build_kpis(df_v, date_from, date_to) if not df_v.empty else []
    zonas_tabla = _build_zonas_tabla(df_v, zonas_info, date_from, date_to) if not df_v.empty else []
    insights = (
        _build_insights(
            df_v,
            zonas_info,
            date_from,
            date_to,
            df_weather_preloaded=df_weather,
            s_cruceros=s_cruceros if tiene_cruceros else None,
        )
        if not df_v.empty
        else []
    )

    # Charts globales
    fig_trafico = _chart_trafico(df_v, zonas_info, date_from, date_to)
    fig_dias = _chart_dias_vs_prev(df_v, date_from, date_to, dias)
    fig_embudo = _chart_embudo(zonas_info, df_v, date_from, date_to)
    fig_temp = _chart_temperatura(df_weather, date_from, date_to) if not df_weather.empty else None
    fig_cruc = _chart_cruceros(s_cruceros, date_from, date_to) if tiene_cruceros else None

    chart_trafico_b64 = _fig_to_b64(fig_trafico, width=900, height=290)
    chart_dias_b64 = _fig_to_b64(fig_dias, width=900, height=240)
    chart_embudo_b64 = (
        _fig_to_b64(fig_embudo, width=900, height=fig_embudo.layout.height) if fig_embudo else ""
    )
    chart_temp_b64 = _fig_to_b64(fig_temp, width=900, height=180) if fig_temp else ""
    chart_cruc_b64 = _fig_to_b64(fig_cruc, width=900, height=180) if fig_cruc else ""

    # Capítulos mensuales (solo para períodos > 21 días)
    capitulos = []
    if dias > 21 and not df_v.empty:
        capitulos = _build_capitulos(df_v, zonas_info, df_weather, s_cruceros, date_from, date_to)

    # Índice dinámico
    tiene_clima = bool(chart_temp_b64 or chart_cruc_b64)
    pg_zonas = 5 + (1 if tiene_clima else 0)
    index_sections = [
        {
            "title": "Conclusiones del período",
            "desc": "Análisis automático con cruceros, clima y zonas",
            "page": 3,
        },
        {
            "title": "Resumen ejecutivo",
            "desc": f"4 KPIs · {period_short} vs {prev_short}",
            "page": 3,
        },
        {
            "title": "Tráfico por período",
            "desc": "Exterior e interior · escala independiente por fila",
            "page": 4,
        },
        {
            "title": "Distribución por día de semana",
            "desc": "Comparativa actual vs. período anterior",
            "page": 4,
        },
    ]
    if tiene_clima:
        index_sections.append(
            {
                "title": "Clima y cruceros",
                "desc": "Temperatura del período · pasajeros de crucero por escala",
                "page": 5,
            }
        )
    index_sections.append(
        {
            "title": "Análisis por zona",
            "desc": f"{len(zonas_tabla)} zonas · visitas, var., estancia",
            "page": pg_zonas,
        }
    )
    if chart_embudo_b64:
        index_sections.append(
            {"title": "Embudo de conversión", "desc": "Exterior, Tienda, Caja", "page": pg_zonas}
        )
    for cap in capitulos:
        index_sections.append(
            {
                "title": f"Capítulo {cap['num']}: {cap['mes_label'].title()}",
                "desc": "Análisis diario, semanal, clima y cruceros del mes",
                "page": pg_zonas + cap["num"],
            }
        )

    # Render
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))
    html_str = env.get_template("informe_miniso.html").render(
        org_nombre=branding.nombre,
        loc_nombre=loc_nombre,
        ciudad=ciudad,
        tipo_periodo=period,
        period_short=period_short,
        prev_short=prev_short,
        period_full=period_full,
        prev_full=prev_full,
        date_generated=_short(datetime.today()),
        kpis=kpis,
        chart_trafico_b64=chart_trafico_b64,
        chart_dias_b64=chart_dias_b64,
        chart_embudo_b64=chart_embudo_b64,
        chart_temp_b64=chart_temp_b64,
        chart_cruc_b64=chart_cruc_b64,
        tiene_cruceros=tiene_cruceros,
        tiene_clima=tiene_clima,
        zonas_tabla=zonas_tabla,
        insights=insights,
        index_sections=index_sections,
        logo_b64=logo_b64,
        capitulos=capitulos,
    )

    return HTML(string=html_str, base_url=str(_ASSETS_DIR)).write_pdf()
