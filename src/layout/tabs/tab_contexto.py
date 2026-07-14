from datetime import datetime

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update

from src.data_processing.supercalendario import CALENDARIO_FEATURE_COLS, get_calendario_features
from src.db.queries import (
    get_df_enriquecido,
    get_señal_diaria,
    get_señales_propias_meta,
    get_zones_for_loc,
)
from src.layout.components.loaders import loading_zone

# ── Signal catalog ─────────────────────────────────────────────────────────────

_SIGNALS: dict[str, dict] = {
    "temp_max": {
        "label": "Temperatura máxima",
        "type": "continuous",
        "unit": "°C",
        "color": "#e74c3c",
        "agg": "max",
        "always_visible": True,
        "on_label": None,
    },
    "temp_min": {
        "label": "Temperatura mínima",
        "type": "continuous",
        "unit": "°C",
        "color": "#3498db",
        "agg": "min",
        "always_visible": True,
        "on_label": None,
    },
    "llueve": {
        "label": "Lluvia",
        "type": "binary",
        "unit": "",
        "color": "#5dade2",
        "on_label": "los días con lluvia",
        "agg": "max",
        "always_visible": True,
    },
    "es_festivo": {
        "label": "Festivo nacional",
        "type": "binary",
        "unit": "",
        "color": "#f39c12",
        "on_label": "los festivos nacionales",
        "agg": "max",
        "always_visible": True,
    },
    "es_finde": {
        "label": "Fin de semana",
        "type": "binary",
        "unit": "",
        "color": "#8e44ad",
        "on_label": "los fines de semana",
        "agg": "max",
        "always_visible": True,
    },
    "es_rebajas_invierno": {
        "label": "Rebajas de invierno",
        "type": "binary",
        "unit": "",
        "color": "#e67e22",
        "on_label": "el período de rebajas de invierno",
        "agg": "max",
        "always_visible": False,
    },
    "es_rebajas_verano": {
        "label": "Rebajas de verano",
        "type": "binary",
        "unit": "",
        "color": "#27ae60",
        "on_label": "el período de rebajas de verano",
        "agg": "max",
        "always_visible": False,
    },
    "es_black_friday_semana": {
        "label": "Black Friday",
        "type": "binary",
        "unit": "",
        "color": "#2c3e50",
        "on_label": "la semana de Black Friday",
        "agg": "max",
        "always_visible": False,
    },
    "es_cyber_monday": {
        "label": "Cyber Monday",
        "type": "binary",
        "unit": "",
        "color": "#34495e",
        "on_label": "el Cyber Monday",
        "agg": "max",
        "always_visible": False,
    },
    "es_navidad_compras": {
        "label": "Período de Navidad",
        "type": "binary",
        "unit": "",
        "color": "#c0392b",
        "on_label": "el período de Navidad",
        "agg": "max",
        "always_visible": False,
    },
    "es_reyes_compras": {
        "label": "Período de Reyes",
        "type": "binary",
        "unit": "",
        "color": "#9b59b6",
        "on_label": "el período de Reyes",
        "agg": "max",
        "always_visible": False,
    },
    "es_san_valentin_ventana": {
        "label": "San Valentín",
        "type": "binary",
        "unit": "",
        "color": "#e91e8c",
        "on_label": "la ventana de San Valentín",
        "agg": "max",
        "always_visible": False,
    },
    "es_dia_madre_ventana": {
        "label": "Día de la Madre",
        "type": "binary",
        "unit": "",
        "color": "#ff6b6b",
        "on_label": "la ventana del Día de la Madre",
        "agg": "max",
        "always_visible": False,
    },
}

# Carpetas de señales estándar (orden de aparición)
_SIGNAL_GROUPS = [
    ("Clima", ["temp_max", "temp_min", "llueve"]),
    ("Calendario", ["es_festivo", "es_finde"]),
    (
        "Eventos comerciales",
        [
            "es_rebajas_invierno",
            "es_rebajas_verano",
            "es_black_friday_semana",
            "es_cyber_monday",
            "es_navidad_compras",
            "es_reyes_compras",
            "es_san_valentin_ventana",
            "es_dia_madre_ventana",
        ],
    ),
]

_CAL_COLS = set(CALENDARIO_FEATURE_COLS) & set(_SIGNALS.keys())
_ZONE_COLORS = ["#0052CC", "#e67e22", "#27ae60", "#8e44ad", "#e74c3c", "#1abc9c", "#2980b9"]
_CFG_ZONE = {"displayModeBar": False, "scrollZoom": False}

_RANGE_BUTTONS = [
    dict(count=7, label="Última semana", step="day", stepmode="backward"),
    dict(count=14, label="Semana pasada", step="day", stepmode="backward"),
    dict(count=1, label="Mes actual", step="month", stepmode="todate"),
    dict(count=1, label="Mes anterior", step="month", stepmode="backward"),
    dict(count=3, label="3 meses", step="month", stepmode="backward"),
    dict(step="all", label="Todo"),
]

_HEADER_STYLE = {
    "fontSize": "0.67rem",
    "fontWeight": "700",
    "letterSpacing": "0.9px",
    "color": "#8492a6",
    "textTransform": "uppercase",
    "display": "block",
    "paddingTop": "12px",
    "paddingBottom": "3px",
    "borderTop": "1px solid #e9ecef",
    "marginTop": "4px",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _hex_to_rgb(h: str) -> str:
    h = h.lstrip("#")
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"


def _header_option(group_name: str) -> dict:
    return {
        "label": html.Span(group_name, style=_HEADER_STYLE),
        "value": f"__h_{group_name}",
        "disabled": True,
    }


def _signal_option(col: str, meta: dict) -> dict:
    return {
        "label": html.Span(
            [
                html.Span(
                    style={
                        "display": "inline-block",
                        "width": "8px",
                        "height": "8px",
                        "borderRadius": "50%",
                        "background": meta["color"],
                        "marginRight": "8px",
                        "flexShrink": "0",
                    }
                ),
                meta["label"],
            ],
            className="d-flex align-items-center",
            style={"fontSize": "0.82rem"},
        ),
        "value": col,
    }


def _get_senales_propias(loc_uuid: str) -> list[dict]:
    """
    Devuelve [{'col': señal_id, 'meta': _SIGNALS-compatible dict}] para las
    señales externas activas de la ubicación, excluyendo las señales estándar
    que ya aparecen en las carpetas Clima/Calendario.
    """
    if not loc_uuid:
        return []
    try:
        meta_dict = get_señales_propias_meta(loc_uuid)
    except Exception:
        return []
    return [
        {
            "col": sid,
            "meta": {
                "label": m["label"],
                "type": "continuous",
                "unit": m.get("sublabel", ""),
                "color": m["color"],
                "agg": m.get("agg_fn", "sum"),
                "always_visible": False,
                "on_label": None,
            },
        }
        for sid, m in meta_dict.items()
        if sid not in _SIGNALS  # evitar duplicar señales ya en las carpetas estándar
    ]


def _compute_options(
    df: pd.DataFrame,
    sig_col: str,
    propias: list[dict] | None = None,
) -> tuple[list[dict], str]:
    active_cal = {col for col in _CAL_COLS if col in df.columns and df[col].sum() > 0}
    options: list[dict] = []
    available: list[str] = []

    for group_name, cols in _SIGNAL_GROUPS:
        group_opts = []
        for col in cols:
            meta = _SIGNALS[col]
            if meta["always_visible"] or col in active_cal:
                group_opts.append(_signal_option(col, meta))
                available.append(col)
        if group_opts:
            options.append(_header_option(group_name))
            options.extend(group_opts)

    # Carpeta de señales propias
    propias = propias or []
    options.append(_header_option("Señales propias"))
    if propias:
        for s in propias:
            options.append(_signal_option(s["col"], s["meta"]))
            available.append(s["col"])
    else:
        options.append(
            {
                "label": html.Span(
                    "Sin señales propias configuradas para esta ubicación.",
                    className="fst-italic text-muted",
                    style={"fontSize": "0.75rem", "paddingLeft": "4px"},
                ),
                "value": "__placeholder_propias",
                "disabled": True,
            }
        )

    current = sig_col if sig_col in available else (available[0] if available else "temp_max")
    return options, current


def _build_zone_chart(
    df_merged: pd.DataFrame,
    sig_col: str,
    zone_color: str,
    default_start: str,
    default_end: str,
    meta: dict | None = None,
) -> go.Figure:
    """df_merged: columnas fecha (datetime), total_visits, <sig_col>."""
    meta = meta or _SIGNALS[sig_col]
    sig_color = meta["color"]
    sig_label = meta["label"]
    sig_type = meta["type"]
    sig_unit = meta.get("unit", "")

    dates = df_merged["fecha"].tolist()
    visits = df_merged["total_visits"].fillna(0).tolist()
    sig_y = df_merged[sig_col].tolist()

    fig = go.Figure()

    # Franjas mensuales alternadas
    min_d = df_merged["fecha"].min()
    max_d = df_merged["fecha"].max()
    month_starts = pd.date_range(
        min_d.replace(day=1),
        max_d + pd.offsets.MonthBegin(1),
        freq="MS",
    )
    for i, ms in enumerate(month_starts):
        me = ms + pd.offsets.MonthEnd(1)
        if i % 2 == 0:
            fig.add_vrect(
                x0=ms.strftime("%Y-%m-%d"),
                x1=min(me, max_d + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                fillcolor="rgba(0,0,0,0.035)",
                line_width=0,
                layer="below",
            )

    # Guías de inicio de semana
    for w in pd.date_range(min_d, max_d, freq="W-MON"):
        fig.add_vline(
            x=w.strftime("%Y-%m-%d"),
            line=dict(color="rgba(100,100,100,0.10)", width=0.8),
            layer="below",
        )

    # Entradas de leyenda para elementos contextuales
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(color="rgba(0,0,0,0.07)", size=12, symbol="square"),
            name="Franja mensual (alternada)",
            showlegend=True,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            line=dict(color="rgba(100,100,100,0.20)", width=1.2),
            name="Inicio de semana",
            showlegend=True,
        )
    )

    # Barras de visitas
    fig.add_trace(
        go.Bar(
            x=dates,
            y=visits,
            name="Visitas",
            marker=dict(color=zone_color, opacity=0.82, cornerradius=2),
            yaxis="y",
            hovertemplate="<b>%{y:,}</b> visitas · %{x|%-d %b %Y}<extra></extra>",
        )
    )

    # Señal en eje secundario
    if sig_type == "binary":
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=sig_y,
                name=sig_label,
                mode="none",
                fill="tozeroy",
                fillcolor=f"rgba({_hex_to_rgb(sig_color)},0.18)",
                yaxis="y2",
                hovertemplate=f"{sig_label}<extra></extra>",
            )
        )
        y2_range = [0, 1.8]
        y2_title = sig_label
    else:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=sig_y,
                name=sig_label,
                mode="lines",
                line=dict(color=sig_color, width=2.2),
                yaxis="y2",
                hovertemplate=f"%{{x|%-d %b}}: <b>%{{y:.1f}}{sig_unit}</b><extra></extra>",
            )
        )
        y2_range = None
        y2_title = f"{sig_label} ({sig_unit})" if sig_unit else sig_label

        if sig_col == "temp_max" and df_merged[sig_col].max() >= 28:
            fig.add_hline(
                y=32,
                line=dict(color=sig_color, dash="dot", width=1),
                annotation_text="32 °C",
                annotation_position="top right",
                annotation_font_size=9,
                annotation_font_color=sig_color,
                yref="y2",
            )

    # Marcador "Hoy"
    today_str = datetime.today().strftime("%Y-%m-%d")
    if min_d.strftime("%Y-%m-%d") <= today_str <= max_d.strftime("%Y-%m-%d"):
        fig.add_vline(
            x=today_str,
            line=dict(color="#0052CC", width=1.5, dash="dash"),
            annotation_text="Hoy",
            annotation_position="top",
            annotation_font_size=9,
            annotation_font_color="#0052CC",
        )
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color="#0052CC", width=1.5, dash="dash"),
                name="Hoy",
                showlegend=True,
            )
        )

    fig.update_layout(
        height=520,
        margin=dict(t=55, b=10, l=60, r=90),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.10,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=10, color="#2c3e50"),
            bgcolor="rgba(255,255,255,0.88)",
            bordercolor="#dee2e6",
            borderwidth=1,
        ),
        yaxis=dict(
            title="Visitas",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            tickfont=dict(size=9),
            rangemode="tozero",
        ),
        yaxis2=dict(
            title=y2_title,
            overlaying="y",
            side="right",
            tickfont=dict(size=9),
            showgrid=False,
            **({"range": y2_range} if y2_range else {}),
        ),
        xaxis=dict(
            type="date",
            showgrid=False,
            tickformat="%-d %b\n%Y",
            tickfont=dict(size=9),
            range=[default_start, default_end],
            rangeselector=dict(
                buttons=_RANGE_BUTTONS,
                bgcolor="rgba(248,249,250,0.95)",
                activecolor="#0052CC",
                bordercolor="#dee2e6",
                borderwidth=1,
                font=dict(size=11, color="#495057", family="inherit"),
                x=0,
                xanchor="left",
                y=1.18,
                yanchor="top",
            ),
            rangeslider=dict(
                visible=True,
                thickness=0.07,
                bgcolor="rgba(248,249,250,0.90)",
                bordercolor="#dee2e6",
                borderwidth=1,
            ),
        ),
    )

    return fig


def _build_zone_insight(
    zone_visits: pd.DataFrame,
    df_sig: pd.DataFrame,
    sig_col: str,
    meta: dict | None = None,
) -> html.Div:
    """Reflexión estadística para una zona concreta. zone_visits: [fecha, total_visits]."""
    meta = meta or _SIGNALS[sig_col]
    sig_type = meta["type"]
    sig_label = meta["label"].lower()

    merged = pd.merge(df_sig[["fecha", sig_col]], zone_visits, on="fecha", how="inner")
    visits = merged["total_visits"].values.astype(float)
    signal = merged[sig_col].values.astype(float)
    n = len(merged)

    if n < 5:
        return html.Div()

    fecha_min = pd.to_datetime(merged["fecha"].min()).strftime("%-d de %B de %Y")
    fecha_max = pd.to_datetime(merged["fecha"].max()).strftime("%-d de %B de %Y")
    ventana = f"el período comprendido entre el {fecha_min} y el {fecha_max}"

    if sig_type == "continuous":
        mask = ~(np.isnan(visits) | np.isnan(signal))
        if mask.sum() < 5:
            return html.Div()
        if np.std(signal[mask]) < 1e-9 or np.std(visits[mask]) < 1e-9:
            return html.Div(
                html.P(
                    "Sin variación suficiente en el período analizado para calcular correlación.",
                    className="text-muted small mb-0",
                ),
                className="p-3 rounded-3 mt-2",
                style={"background": "#f8f9fa", "borderLeft": f"3px solid {meta['color']}"},
            )
        r = float(np.corrcoef(visits[mask], signal[mask])[0, 1])
        abs_r = abs(r)

        if abs_r >= 0.7:
            intensidad = "fuerte"
        elif abs_r >= 0.4:
            intensidad = "moderada"
        elif abs_r >= 0.2:
            intensidad = "débil"
        else:
            intensidad = "muy débil o prácticamente nula"

        direccion = "directa" if r >= 0 else "inversa"
        efecto = (
            "las jornadas con valores más elevados de esta variable tienden a coincidir con mayor afluencia"
            if r >= 0
            else "las jornadas con valores más elevados de esta variable tienden a coincidir con menor afluencia"
        )

        parrafos = [
            f"En {ventana}, la correlación de Pearson entre {sig_label} y la afluencia "
            f"alcanza un valor de {r:.2f}, lo que indica una asociación {direccion} "
            f"de intensidad {intensidad}. En términos prácticos, {efecto} "
            f"a lo largo del período analizado ({n} días)."
        ]

        if sig_col == "temp_max":
            hot = merged[signal >= 32]
            cold = merged[signal < 32]
            if len(hot) > 2 and len(cold) > 2 and cold["total_visits"].mean() > 0:
                diff = (
                    (hot["total_visits"].mean() - cold["total_visits"].mean())
                    / cold["total_visits"].mean()
                    * 100
                )
                comparacion = "superiores" if diff > 0 else "inferiores"
                parrafos.append(
                    f"Los {len(hot)} días con temperatura máxima igual o superior a 32 grados "
                    f"registran una afluencia media de {hot['total_visits'].mean():,.0f} visitantes, "
                    f"frente a {cold['total_visits'].mean():,.0f} en el resto, lo que representa una "
                    f"variación del {abs(diff):.0f}% {comparacion}."
                )
    else:
        on_label = meta.get("on_label") or sig_label
        v_on = visits[signal >= 0.5]
        v_off = visits[signal < 0.5]
        n_on = len(v_on)

        if n_on == 0:
            return html.Div(
                html.P(
                    f"No se registran períodos activos de {on_label} en la ventana analizada.",
                    className="text-muted small mb-0",
                ),
                className="p-3 rounded-3 mt-2",
                style={"background": "#f8f9fa", "borderLeft": f"3px solid {meta['color']}"},
            )

        mean_on = float(v_on.mean())
        mean_off = float(v_off.mean()) if len(v_off) > 0 else 0.0
        pct = (mean_on - mean_off) / mean_off * 100 if mean_off > 0 else 0.0
        abs_pct = abs(pct)

        if abs_pct < 5:
            descripcion = (
                f"La afluencia en {on_label} ({n_on} días) es prácticamente equivalente "
                f"a la del resto del período: {mean_on:,.0f} visitantes de media frente a {mean_off:,.0f}, "
                f"con una diferencia del {abs_pct:.1f}% que no resulta estadísticamente relevante."
            )
        elif pct > 0:
            descripcion = (
                f"Los {n_on} días correspondientes a {on_label} presentan una afluencia media de "
                f"{mean_on:,.0f} visitantes, lo que supone un incremento del {abs_pct:.0f}% respecto "
                f"a los períodos fuera de dicha categoría, donde la media se sitúa en {mean_off:,.0f} visitantes."
            )
        else:
            descripcion = (
                f"Los {n_on} días correspondientes a {on_label} registran una afluencia media de "
                f"{mean_on:,.0f} visitantes, un {abs_pct:.0f}% inferior a los {mean_off:,.0f} visitantes "
                f"de media registrados fuera de dicho período."
            )

        parrafos = [f"En {ventana} se identifican {n_on} días dentro de {on_label}. {descripcion}"]

        if abs_pct >= 5:
            parrafos.append(
                "Este diferencial positivo sugiere que el establecimiento concentra una mayor actividad "
                "comercial durante este período, lo que puede orientar las decisiones de planificación "
                "de personal y gestión de stock."
                if pct > 0
                else "Este diferencial negativo puede reflejar una caída en la afluencia espontánea, "
                "susceptible de compensarse mediante acciones de atracción específicas durante el período."
            )

    return html.Div(
        [
            html.P(p, className="mb-2 small", style={"color": "#2c3e50", "lineHeight": "1.70"})
            for p in parrafos
        ],
        className="p-3 rounded-3 mt-2",
        style={"background": "#f8f9fa", "borderLeft": f"3px solid {meta['color']}"},
    )


# ── Layout ─────────────────────────────────────────────────────────────────────


def build_tab_contexto():
    return dcc.Tab(
        label="Factores",
        value="tab-contexto",
        className="fw-bold text-muted",
        children=[
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.H4(
                                        [
                                            html.I(
                                                className="fas fa-layer-group me-2 text-primary"
                                            ),
                                            "Contexto de visitas",
                                        ],
                                        className="fw-bold mb-1 text-dark",
                                    ),
                                    html.P(
                                        "Compara la afluencia observada con señales externas. "
                                        "Usa la barra inferior de cada gráfico para desplazarte en el tiempo "
                                        "y los presets para saltar a períodos concretos.",
                                        className="text-muted small mb-0",
                                    ),
                                ],
                                width=12,
                            ),
                        ],
                        className="mb-4",
                    ),
                    dbc.Row(
                        [
                            # Panel de señales agrupadas por carpeta
                            dbc.Col(
                                [
                                    html.P(
                                        "SEÑALES",
                                        className="text-muted fw-bold mb-2",
                                        style={"fontSize": "0.72rem", "letterSpacing": "0.8px"},
                                    ),
                                    dbc.RadioItems(
                                        id="contexto-sig-selector",
                                        options=[],
                                        value="temp_max",
                                        class_name="vstack gap-1",
                                        input_class_name="btn-check",
                                        label_class_name="btn btn-outline-secondary btn-sm text-start w-100",
                                        label_checked_class_name="btn btn-primary btn-sm text-start w-100",
                                    ),
                                ],
                                width=3,
                                className="pe-4 border-end",
                            ),
                            # Gráficos (uno por zona, con reflexión embebida)
                            dbc.Col(
                                loading_zone(
                                    html.Div(
                                        id="contexto-zones-content",
                                        style={"minHeight": "400px"},
                                    ),
                                    label="Calculando...",
                                    min_height="400px",
                                    delay_show=250,
                                ),
                                width=9,
                            ),
                        ],
                        className="g-3",
                    ),
                ],
                className="p-3",
            )
        ],
    )


# ── Callbacks ──────────────────────────────────────────────────────────────────


@callback(
    Output("contexto-zones-content", "children"),
    Output("contexto-sig-selector", "options"),
    Output("contexto-sig-selector", "value"),
    Input("tabs-panel", "value"),
    Input("drop-locs", "value"),
    Input("contexto-sig-selector", "value"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def actualizar_contexto(tab, locs, sig_col, session_id):
    if tab != "tab-contexto":
        return no_update, no_update, no_update

    empty = html.Div(
        [
            html.I(className="fas fa-layer-group fa-2x text-muted mb-3"),
            html.P("Selecciona una ubicación para ver el análisis.", className="text-muted"),
        ],
        className="text-center py-5",
    )
    if not locs:
        return empty, [], "temp_max"

    loc_uuid = locs[0]
    if not sig_col:
        sig_col = "temp_max"

    df = get_df_enriquecido(loc_uuid, session_id=session_id or "")
    if df.empty:
        return empty, [], "temp_max"

    df["fecha"] = pd.to_datetime(df["fecha"])

    # Zonas padre
    all_zones = [z for z in get_zones_for_loc(loc_uuid) if not z.get("oculta")]
    parent_zones = [z for z in all_zones if not z.get("parent_zona_id")]
    if not parent_zones:
        parent_zones = all_zones[:1]
    parent_ids = {z["zona_id"] for z in parent_zones}

    # Visitas diarias por zona
    df_zones = (
        df[df["zona_id"].isin(parent_ids)]
        .groupby(["fecha", "zona_id"])["total_visits"]
        .sum()
        .reset_index()
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    # Señales diarias a nivel de ubicación
    df_sig = (
        df.groupby("fecha")
        .agg(
            temp_max=("temp_max", "max"),
            temp_min=("temp_min", "min"),
            llueve=("llueve", "max"),
            es_festivo=("es_festivo", "max"),
        )
        .reset_index()
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    df_sig["fecha"] = pd.to_datetime(df_sig["fecha"])
    df_sig["es_finde"] = df_sig["fecha"].dt.dayofweek.isin([5, 6]).astype(int)

    # Eventos de calendario
    cal_rows = pd.DataFrame(
        [get_calendario_features(f) for f in df_sig["fecha"]],
        index=df_sig.index,
    )
    for col in _CAL_COLS:
        df_sig[col] = cal_rows[col].values

    # Señales propias de esta ubicación (consulta la DB una vez)
    propias = _get_senales_propias(loc_uuid)
    propias_by_col = {p["col"]: p["meta"] for p in propias}

    # Opciones agrupadas por carpeta
    options, sig_col = _compute_options(df_sig, sig_col, propias)

    # Si la señal seleccionada es propia, carga sus valores desde valores_señales
    sig_meta: dict | None = None
    if sig_col not in _SIGNALS and sig_col in propias_by_col:
        sig_meta = propias_by_col[sig_col]
        try:
            serie = get_señal_diaria(
                loc_uuid,
                sig_col,
                df_sig["fecha"].min(),
                df_sig["fecha"].max(),
            )
            df_sig = df_sig.copy()
            df_sig[sig_col] = df_sig["fecha"].map(serie.to_dict()).fillna(0.0)
        except Exception:
            df_sig = df_sig.copy()
            df_sig[sig_col] = 0.0

    # Rango por defecto: últimos 3 meses
    max_date = df_sig["fecha"].max()
    default_start = (max_date - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    default_end = max_date.strftime("%Y-%m-%d")

    # Una tarjeta por zona padre: gráfico + reflexión embebida
    zone_cards = []
    for i, zone in enumerate(parent_zones):
        color = _ZONE_COLORS[i % len(_ZONE_COLORS)]

        zone_visits = df_zones[df_zones["zona_id"] == zone["zona_id"]][
            ["fecha", "total_visits"]
        ].copy()

        df_merged = pd.merge(df_sig[["fecha", sig_col]], zone_visits, on="fecha", how="left")
        df_merged["total_visits"] = df_merged["total_visits"].fillna(0)

        fig = _build_zone_chart(
            df_merged, sig_col, color, default_start, default_end, meta=sig_meta
        )
        insight = _build_zone_insight(zone_visits, df_sig, sig_col, meta=sig_meta)

        zone_cards.append(
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(
                            [
                                html.Span(
                                    style={
                                        "display": "inline-block",
                                        "width": "10px",
                                        "height": "10px",
                                        "borderRadius": "50%",
                                        "background": color,
                                        "marginRight": "8px",
                                    }
                                ),
                                html.Span(
                                    zone["nombre"],
                                    className="fw-bold text-dark",
                                    style={
                                        "fontSize": "0.82rem",
                                        "textTransform": "uppercase",
                                        "letterSpacing": "0.5px",
                                    },
                                ),
                            ],
                            className="d-flex align-items-center mb-2",
                        ),
                        dcc.Graph(
                            figure=fig,
                            config=_CFG_ZONE,
                            style={"height": "520px"},
                        ),
                        insight,
                    ],
                    className="p-3",
                ),
                className="border-0 shadow-sm rounded-4 mb-4",
            )
        )

    return html.Div(zone_cards), options, sig_col
