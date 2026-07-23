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

import calendar
import os
import re
from datetime import date, timedelta

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from src.core import data_master as _dm
from src.core.theme import (
    C_AMBER as _C_AMBER,
)
from src.core.theme import (
    C_DANGER as _C_DANGER,
)
from src.core.theme import (
    C_DARK as _C_DARK,
)
from src.core.theme import (
    C_MUTED as _C_MUTED,
)
from src.core.theme import (
    C_SUCCESS as _C_SUCCESS,
)
from src.core.theme import (
    CFG_GRAPH as _CFG_GRAPH,
)
from src.core.theme import (
    PALETA_PM as _PALETA_PM,
)
from src.core.utils import MESES_ES as _MESES_ES
from src.data_processing.geo_enrichment import get_geo_snapshot_date, get_geo_vals
from src.db.queries import get_location_by_name

# ── Sub-module imports ────────────────────────────────────────────────────────
from src.reporting._hc_charts import (  # noqa: E402
    _fig_dias_semana,
    _fig_finde_vs_laborable,
    _fig_hora_pico,
    _fig_lluvia_trafico,
    _fig_nuevos_ratio,
    _fig_semanas_mes,
    _fig_sparkline,
    _fig_temperatura_trafico,
)
from src.reporting._hc_charts import (
    _fig_dwell_zonas as _fig_dwell_zonas_base,
)
from src.reporting._hc_charts import (
    _fig_embudo_conversion as _fig_embudo_conversion_base,
)
from src.reporting._hc_informe_tabs import render_informe_tabs, render_periodo_calendar
from src.reporting.geo_panel import generar_mapa_contexto, generar_panel_geo_visual


def _clima_historico(lat: float, lon: float, fecha_inicio: str, fecha_fin: str) -> dict:
    import requests

    try:
        url = (
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={fecha_inicio}&end_date={fecha_fin}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone=Europe%2FMadrid"
        )
        d = requests.get(url, timeout=5).json().get("daily", {})
        return {
            dia: {
                "tmax": d["temperature_2m_max"][i],
                "tmin": d["temperature_2m_min"][i],
                "precip": d["precipitation_sum"][i],
            }
            for i, dia in enumerate(d.get("time", []))
        }
    except Exception:
        return {}


dias_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
dias_corto = ["L", "M", "X", "J", "V", "S", "D"]


# ── Zone helpers — display metadata desde tipos_zona ─────────────────────────


def _detect_zone_type(zona: str, zone_enum: int | None = None) -> str:
    """Mapea la zona a un zone_type canónico. Prefiere zone_enum sobre el nombre."""
    if zone_enum is not None:
        return {0: "caja", 1: "tienda", 2: "exterior"}.get(zone_enum, "default")
    zl = str(zona).lower()
    if "caja" in zl:
        return "caja"
    if "tienda" in zl:
        return "tienda"
    if "calle" in zl or "exterior" in zl:
        return "exterior"
    return "default"


def _load_zone_meta(conn) -> dict:
    """Devuelve {zone_type: {label, icon_cls, color, tooltip}} desde DB."""
    try:
        rows = conn.execute(
            "SELECT tipo_zona, label, icono, color, tooltip FROM tipos_zona"
        ).fetchall()
        return {
            zt: {"label": lbl, "icon_cls": icon, "color": col, "tooltip": tt or ""}
            for zt, lbl, icon, col, tt in rows
        }
    except Exception:
        return {}


def _zone_display(zona: str, zone_meta: dict, zone_enum: int | None = None) -> dict:
    """Devuelve {color, label, icon_cls, tooltip} para la zona. Prefiere zone_enum."""
    zt = _detect_zone_type(zona, zone_enum)
    m = zone_meta.get(zt, zone_meta.get("default", {}))
    color = m.get("color") or _PALETA_PM[hash(zona) % len(_PALETA_PM)]
    return {
        "color": color,
        "label": m.get("label", "Analítica"),
        "icon_cls": m.get("icon_cls", "fas fa-layer-group"),
        "tooltip": m.get("tooltip", "Zona de medición de tráfico."),
    }


def _color_zona(zona) -> str:
    """Compat: devuelve el color de una zona usando tipos_zona."""
    try:
        from src.db.store import get_conn

        zm = _load_zone_meta(get_conn())
    except Exception:
        zm = {}
    return _zone_display(zona, zm)["color"]


def _load_norm_tipo(conn) -> dict:
    """Devuelve {raw_event_key: canonical_type} desde feature_registry."""
    try:
        rows = conn.execute(
            "SELECT señal_id, tipo_canonico FROM señales " "WHERE tipo_canonico IS NOT NULL"
        ).fetchall()
        return {fk: canon for fk, canon in rows}
    except Exception:
        return {}


# ── Data helpers ──────────────────────────────────────────────────────────────


def obtener_zonas_validas(ruta=None):
    try:
        from src.db.store import get_conn

        rows = (
            get_conn()
            .execute("SELECT nombre FROM zonas WHERE es_ultima_zona = TRUE AND oculta = FALSE")
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


# ── Chart builders (bodies moved to _hc_charts.py) ───────────────────────────
# Wrappers for _fig_dwell_zonas and _fig_embudo_conversion that inject _color_zona
# so callers in this module see the original signatures without any change.


def _fig_dwell_zonas(zonas_data, child_zones=None, primary_color: str = "#0052CC"):
    """Tiempo medio de permanencia por zona — solo zonas padre."""
    return _fig_dwell_zonas_base(
        zonas_data, child_zones=child_zones, color_fn=_color_zona, primary_color=primary_color
    )


def _fig_embudo_conversion(zonas_data, primary_color: str = "#0052CC"):
    """
    Embudo exterior → tienda → caja con tasa de conversión entre pasos.
    Requiere al menos dos zonas con roles distintos identificables.
    """
    return _fig_embudo_conversion_base(
        zonas_data, color_fn=_color_zona, primary_color=primary_color
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
    zone_enum=None,
    primary_color: str = "#0052CC",
):
    """Tarjeta de zona: % delta en grande (hero) + visitantes absolutos + sparkline."""
    try:
        from src.db.store import get_conn

        _zone_meta = _load_zone_meta(get_conn())
    except Exception:
        _zone_meta = {}
    _zd = _zone_display(zona, _zone_meta, zone_enum=zone_enum)
    color = _zd["color"]
    badge_lbl, tooltip_role = _zd["label"], _zd["tooltip"]
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
            **({"background": f"rgba({_rgb_str(primary_color)},0.04)"} if has_children else {}),
        },
    )


def _render_pm_questions(
    df,
    zonas_data,
    fecha_max,
    uid,
    ventana="semana",
    child_zones=None,
    clima=None,
    primary_color: str = "#0052CC",
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
                _fig_semanas_mes(df, fecha_max, primary_color=primary_color),
                f"q-semanas-{uid}",
                "¿Cómo evolucionó el tráfico semana a semana?",
                f"Visitantes por semana · sólido = {_periodo_corto} · translúcido = {_ant_lbl}",
                "180px",
            )
        )

    preguntas += [
        (
            _fig_dias_semana(df, fecha_max, dias=dias_v, primary_color=primary_color),
            f"q-dias-{uid}",
            "¿Cuándo llegan los visitantes?",
            "Media por día · tono más oscuro = día pico · sólido = actual · translúcido = anterior",
            "165px",
        ),
        (
            _fig_hora_pico(df_top, fecha_max=fecha_max, dias=dias_v, primary_color=primary_color),
            f"q-hora-{uid}",
            "¿A qué hora llegan?",
            "Distribución horaria · barras = actual · línea punteada = anterior",
            "180px",
        ),
        (
            _fig_finde_vs_laborable(df, fecha_max, dias=dias_v, primary_color=primary_color),
            f"q-finde-{uid}",
            "¿Rinde mejor el fin de semana o entre semana?",
            f"Visitantes/día (media) · sólido = actual · translúcido = {_ant_lbl}",
            "180px",
        ),
        (
            _fig_nuevos_ratio(df_top, fecha_max, dias=dias_v, primary_color=primary_color),
            f"q-nuevos-{uid}",
            "¿Cuántos visitantes son nuevos?",
            "% visitantes nuevos · línea azul = media actual · línea punteada tenue = media anterior",
            "180px",
        ),
        (
            _fig_dwell_zonas(zonas_top, child_zones=_cz, primary_color=primary_color),
            f"q-dwell-{uid}",
            "¿Cuánto tiempo se quedan?",
            f"Tiempo medio de permanencia por zona principal · {_periodo_corto}",
            "180px",
        ),
        (
            _fig_embudo_conversion(zonas_top, primary_color=primary_color),
            f"q-embudo-{uid}",
            "¿Cuántos visitantes convierten?",
            f"Visitantes por etapa · {_periodo_corto} · % respecto al paso anterior",
            "180px",
        ),
    ]

    # ── Gráficos de clima (si hay datos disponibles) ───────────────────────
    if clima:
        _ant_lbl_c = "28 días anteriores" if ventana == "mes" else "7 días anteriores"
        fig_temp = _fig_temperatura_trafico(
            df, clima, fecha_max, dias=dias_v, primary_color=primary_color
        )
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
        fig_lluvia = _fig_lluvia_trafico(
            df, clima, fecha_max, dias=dias_v, primary_color=primary_color
        )
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
                            "background": f"rgba({_rgb_str(primary_color)},0.85)",
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
                            "background": f"rgba({_rgb_str(primary_color)},0.14)",
                            "border": f"1px solid rgba({_rgb_str(primary_color)},0.35)",
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

_DEFAULT_COLOR = "#0052CC"


def _load_feature_meta(conn, location_uuid: str) -> dict:
    """
    Returns {señal_id: {"label", "sublabel", "color", "icon_cls", "agg_fn", "display_mode", "notas"}}
    for all features registered in señales that either:
      - have an active/contexto flag for this location (valores_señales / cruceros / calendario features)
      - OR are of display_mode='events_count' (calendar eventos — shown if data exists, no flag needed)
    """
    try:
        rows = conn.execute(
            """SELECT fr.señal_id, fr.label, fr.sublabel, fr.color, fr.icono,
                      fr.funcion_agregacion, COALESCE(fr.modo_visualizacion, 'yoy') AS modo_visualizacion, fr.notas,
                      fr.fallback_señal_id
               FROM señales fr
               WHERE fr.modo_visualizacion = 'events_count'
                  OR EXISTS (
                       SELECT 1 FROM activacion_señales ff
                       WHERE ff.señal_id = fr.señal_id
                         AND ff.ubicacion_id = ?
                         AND ff.status IN ('active', 'contexto')
                  )""",
            [location_uuid],
        ).fetchall()
    except Exception:
        return {}
    return {
        fk: {
            "label": lbl or fk.replace("_", " ").title(),
            "sublabel": sub or "",
            "color": col or "#0052CC",
            "icon_cls": icon or "fas fa-satellite-dish",
            "agg_fn": agg or "sum",
            "display_mode": mode,
            "notas": notas or "",
            "fallback_feature_key": fallback or "",
        }
        for fk, lbl, sub, col, icon, agg, mode, notas, fallback in rows
    }


# ── Shared zone-ordering helper ───────────────────────────────────────────────


def _orden_zona(zona: str, zone_enum: int | None = None) -> int:
    if zone_enum is not None:
        return {2: 0, 1: 1, 0: 2, 3: 3}.get(zone_enum, 3)
    zl = zona.lower()
    if "exterior" in zl or "calle" in zl:
        return 0
    if "tienda" in zl:
        return 1
    if "caja" in zl:
        return 2
    return 3


def _sort_zona_key(zona: str, zone_enum: int | None = None) -> tuple:
    """Sort key: semantic role first, then ascending numeric suffix, then alphabetical."""
    rol = _orden_zona(zona, zone_enum)
    nums = [int(n) for n in re.findall(r"\d+", zona)]
    return (rol, nums[0] if nums else 999, zona.lower())


# ── New "Estado" redesign helpers ─────────────────────────────────────────────


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


_ASSETS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets"
)


def _rgb_str(hex_color: str) -> str:
    """Devuelve 'R,G,B' para usar en rgba() de inline styles."""
    h = hex_color.lstrip("#")
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"


def _darken(hex_color: str, factor: float = 0.75) -> str:
    """Oscurece un color HEX multiplicando RGB por factor."""
    h = hex_color.lstrip("#")
    r = int(int(h[0:2], 16) * factor)
    g = int(int(h[2:4], 16) * factor)
    b = int(int(h[4:6], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _find_hero_image(location_uuid: str | None) -> str | None:
    """Devuelve la URL del hero de la ubicación si existe en assets/locations/, o None."""
    if not location_uuid:
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = os.path.join(_ASSETS_ROOT, "locations", f"{location_uuid}{ext}")
        if os.path.exists(path):
            return f"/assets/locations/{location_uuid}{ext}"
    return None


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
    tooltip_text="",
    icon_cls="fas fa-satellite-dish",
    primary_color="#0052CC",
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
    if all(missing):
        return None

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

    tt_id = f"tt-{re.sub(r'[^a-z0-9]', '-', uid.lower())[:16]}-{re.sub(r'[^a-z0-9]', '-', fk.lower())[:16]}"
    info_els = (
        [
            html.Span(
                html.I(className="fas fa-info-circle", style={"fontSize": "0.75rem"}),
                id=tt_id,
                style={
                    "color": "#ced4da",
                    "cursor": "pointer",
                    "display": "inline-flex",
                    "alignItems": "center",
                    "padding": "0 4px",
                },
            ),
            dbc.Tooltip(
                tooltip_text,
                target=tt_id,
                placement="top",
                style={"fontSize": "0.76rem", "maxWidth": "300px", "textAlign": "left"},
            ),
        ]
        if tooltip_text
        else []
    )

    return html.Div(
        [
            html.Div(
                [
                    html.I(
                        className=f"{icon_cls} me-2",
                        style={"color": color, "fontSize": "0.9rem"},
                    ),
                    html.Span(
                        label,
                        className="fw-semibold me-1",
                        style={"fontSize": "0.9rem", "color": _C_DARK},
                    ),
                    *info_els,
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


def _render_cruceros_section(
    location_uuid: str,
    fecha_max,
    ventana: str = "semana",
    tooltip_text: str = "",
    fallback_feature_key: str = "",
    primary_color: str = "#0052CC",
) -> html.Div | None:
    """Grouped bar: año anterior (ghost) vs año en curso (tier-colored), eje Ene-Dic."""
    try:
        from src.db.store import get_conn

        conn = get_conn()
        desde_yoy = fecha_max - timedelta(days=760)
        yoy_rows = conn.execute(
            """SELECT e.fecha::text, e.valor
               FROM valores_señales e
               JOIN activacion_señales f ON f.señal_id = e.señal_id
                 AND f.ubicacion_id = e.ubicacion_id AND f.status = 'active'
               WHERE e.ubicacion_id = ? AND e.señal_id = 'n_pasajeros_crucero_oficial'
                 AND e.valor IS NOT NULL AND e.fecha >= ?
               ORDER BY e.fecha""",
            [location_uuid, str(desde_yoy.date() if hasattr(desde_yoy, "date") else desde_yoy)],
        ).fetchall()
    except Exception:
        return None

    if not yoy_rows:
        return None

    color = "#1abc9c"
    today = date.today()

    df_y = pd.DataFrame(yoy_rows, columns=["fecha", "value"])
    df_y["fecha"] = pd.to_datetime(df_y["fecha"])

    anio_actual = fecha_max.year if hasattr(fecha_max, "year") else pd.Timestamp(fecha_max).year
    anio_prev = anio_actual - 1

    if df_y[df_y["fecha"].dt.year == anio_actual].empty:
        return None

    # Aggregate daily data into monthly totals
    pax_by_month: dict[str, float] = {}
    for _, row in df_y.iterrows():
        ym = row["fecha"].strftime("%Y-%m")
        pax_by_month[ym] = pax_by_month.get(ym, 0) + (row["value"] or 0)

    # Ship metadata from calendar store
    cruise_meta: dict[str, list[dict]] = {}
    try:
        meta_rows = conn.execute(
            """SELECT fecha_inicio::text, metadata
               FROM eventos
               WHERE ubicacion_id = ? AND evento_key = 'escala_crucero'
                 AND fecha_inicio >= ?
               ORDER BY fecha_inicio""",
            [location_uuid, str(desde_yoy.date() if hasattr(desde_yoy, "date") else desde_yoy)],
        ).fetchall()
        for fecha_str, meta in meta_rows:
            if not meta:
                continue
            dt = pd.Timestamp(fecha_str)
            ym = dt.strftime("%Y-%m")
            barco = (meta.get("barco") or "").strip()[:30]
            pax = meta.get("n_pasajeros") or meta.get("pasajeros") or 0
            cruise_meta.setdefault(ym, []).append({"barco": barco, "pax": int(pax)})
    except Exception:
        pass

    # Previsión from cruise events for any month in the current year where official
    # data is absent (covers both future months and the lag period — months where
    # Puertos del Estado hasn't published yet but we have scheduled cruise calls)
    _fc_by_month: dict[int, float] = {}
    try:
        _fc_rows = conn.execute(
            """SELECT EXTRACT(MONTH FROM fecha_inicio::date)::int,
                      COALESCE(SUM(
                          CASE WHEN (metadata->>'n_pasajeros') ~ '^[0-9]+$'
                               THEN (metadata->>'n_pasajeros')::int ELSE 0 END
                      ), 0)
               FROM   eventos
               WHERE  ubicacion_id = ? AND evento_key = 'escala_crucero'
                 AND  EXTRACT(YEAR FROM fecha_inicio::date)::int = ?
               GROUP  BY 1""",
            [location_uuid, anio_actual],
        ).fetchall()
        _fc_by_month = {int(m): float(v) for m, v in _fc_rows if v and v > 0}
    except Exception:
        pass

    # Fallback (estimación): agrega el feature alternativo por mes para cubrir el lag oficial
    _fallback_by_month: dict[str, float] = {}
    if fallback_feature_key:
        try:
            fb_rows = conn.execute(
                """SELECT fecha::text, valor FROM valores_señales
                   WHERE ubicacion_id = ? AND señal_id = ?
                     AND valor IS NOT NULL AND fecha >= ?""",
                [
                    location_uuid,
                    fallback_feature_key,
                    str(desde_yoy.date() if hasattr(desde_yoy, "date") else desde_yoy),
                ],
            ).fetchall()
            for fs, fv in fb_rows:
                ym = pd.Timestamp(fs).strftime("%Y-%m")
                _fallback_by_month[ym] = _fallback_by_month.get(ym, 0) + (fv or 0)
        except Exception:
            pass

    _C_CONF = _hex_rgba(color, 0.88)
    _C_PROG = _hex_rgba(color, 0.55)
    _C_LAG = _hex_rgba(color, 0.42)
    _C_PREV = _hex_rgba(color, 0.25)
    _C_MISS = "rgba(224,224,224,0.45)"
    _tier_color = {
        "conf": _C_CONF,
        "prog": _C_PROG,
        "lag": _C_LAG,
        "prev": _C_PREV,
        "miss": _C_MISS,
    }

    # ── Build per-month arrays (12 months, Ene-Dic) ───────────────────────────
    meses = list(range(1, 13))
    y_prev: list[float] = []
    y_act: list[float] = []
    act_tiers: list[str] = []
    act_text: list[str] = []
    act_hover: list[str] = []
    prev_hover: list[str] = []

    for m in meses:
        ym_p = f"{anio_prev}-{m:02d}"
        ym_a = f"{anio_actual}-{m:02d}"
        mes_label = _MESES_ES[m - 1]
        last_day_num = calendar.monthrange(anio_actual, m)[1]
        last_of_month = date(anio_actual, m, last_day_num)

        vp = pax_by_month.get(ym_p, 0)
        y_prev.append(vp)
        prev_hover.append(
            f"{mes_label} {anio_prev}: <b>{int(vp):,}</b> pax<extra></extra>"
            if vp > 0
            else f"{mes_label} {anio_prev}: sin datos<extra></extra>"
        )

        # Current year bar
        # Priority: official data → scraping fallback (lag) → event calendar (prev) → miss
        va = pax_by_month.get(ym_a, 0)
        if va > 0:
            tier = "conf" if last_of_month < today else "prog"
        elif ym_a in _fallback_by_month:
            va = _fallback_by_month[ym_a]
            tier = "lag"
        elif m in _fc_by_month:
            va = _fc_by_month[m]
            tier = "prev"
        else:
            tier = "miss"
        y_act.append(va)
        act_tiers.append(tier)
        act_hover.append(
            f"{mes_label} {anio_actual}: <b>{int(va):,}</b> pax<extra></extra>"
            if va > 0
            else f"{mes_label} {anio_actual}: sin datos<extra></extra>"
        )

        # Bar text
        if tier == "miss":
            act_text.append("")
        elif tier == "lag":
            act_text.append(f"<b>{int(va):,}</b><br><i style='font-size:7px'>est.</i>")
        elif tier == "prev":
            act_text.append(f"<b>{int(va):,}</b><br><i style='font-size:7px'>prev.</i>")
        else:
            val_str = f"<b>{int(va):,}</b>"
            if vp > 0:
                pct = (va - vp) / vp * 100
                if abs(pct) < 0.5:
                    act_text.append(val_str)
                elif pct > 0:
                    act_text.append(f"{val_str}<br><span style='color:#27ae60'>▲{pct:+.1f}%</span>")
                else:
                    act_text.append(f"{val_str}<br><span style='color:#e74c3c'>▼{pct:+.1f}%</span>")
            else:
                act_text.append(val_str)

    max_v = max(max(y_prev, default=0), max(y_act, default=0), 1)
    ghost_h = max_v * 0.04

    act_colors = [_tier_color[t] for t in act_tiers]
    y_act_disp = [v if v > 0 else ghost_h for v in y_act]
    y_prev_disp = [v if v > 0 else ghost_h for v in y_prev]
    act_text_pos = ["outside" if t != "miss" else "inside" for t in act_tiers]

    fig = go.Figure()

    # Año anterior — barras fantasma
    fig.add_trace(
        go.Bar(
            x=_MESES_ES,
            y=y_prev_disp,
            name=str(anio_prev),
            marker=dict(
                color=_hex_rgba(color, 0.15),
                line=dict(color=_hex_rgba(color, 0.4), width=1),
                cornerradius=4,
            ),
            text=[""] * 12,
            hovertemplate=prev_hover,
            showlegend=True,
        )
    )

    # Año en curso — barras con colores tier
    fig.add_trace(
        go.Bar(
            x=_MESES_ES,
            y=y_act_disp,
            name=str(anio_actual),
            marker=dict(color=act_colors, cornerradius=4),
            text=act_text,
            textposition=act_text_pos,
            textfont=dict(size=8),
            hovertemplate=act_hover,
            showlegend=True,
        )
    )

    # Vertical "hoy" line at current month
    cur_mes_label = _MESES_ES[today.month - 1]
    fig.add_shape(
        type="line",
        x0=cur_mes_label,
        x1=cur_mes_label,
        y0=0,
        y1=1,
        xref="x",
        yref="paper",
        line=dict(color=f"rgba({_rgb_str(primary_color)},0.45)", width=1.5, dash="dot"),
    )
    fig.add_annotation(
        x=cur_mes_label,
        y=1.01,
        xref="x",
        yref="paper",
        text="hoy",
        showarrow=False,
        yanchor="bottom",
        font=dict(size=8, color=f"rgba({_rgb_str(primary_color)},0.7)"),
    )

    fig.update_layout(
        height=230,
        margin=dict(t=20, b=30, l=10, r=10),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        barmode="group",
        xaxis=dict(showgrid=False, tickfont=dict(size=9), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.55]),
        legend=dict(orientation="h", x=0, y=1.08, font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
    )

    # ── KPI del período ────────────────────────────────────────────────────────
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
                    f"{val_txt} pax este {per_lbl} · ={pct:+.1f}%",
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

    # ── Leyenda: puntos de color + listas de barcos por año ───────────────────
    def _dot(op, bdr=""):
        return html.Span(
            style={
                "display": "inline-block",
                "width": "8px",
                "height": "8px",
                "background": color,
                "opacity": op,
                "flexShrink": 0,
                "border": bdr,
                "borderRadius": "2px",
                "marginRight": "4px",
            }
        )

    tier_legend = html.Div(
        [
            html.Div(
                [_dot("0.88"), html.Span("Real", style={"fontSize": "0.62rem", "color": _C_DARK})],
                className="d-flex align-items-center gap-1",
            ),
            html.Div(
                [
                    _dot("0.55"),
                    html.Span("En curso", style={"fontSize": "0.62rem", "color": _C_MUTED}),
                ],
                className="d-flex align-items-center gap-1",
            ),
            html.Div(
                [
                    _dot("0.25"),
                    html.Span("Previsión", style={"fontSize": "0.62rem", "color": _C_MUTED}),
                ],
                className="d-flex align-items-center gap-1",
            ),
        ],
        className="d-flex gap-3 mb-1",
    )

    def _ship_list(year: int) -> html.Div:
        seen: set = set()
        els: list = []
        for m in meses:
            ym = f"{year}-{m:02d}"
            for s in cruise_meta.get(ym, []):
                key = (s["barco"], ym)
                if key in seen or not s["barco"]:
                    continue
                seen.add(key)
                pax_txt = f" · {s['pax']:,} pax" if s["pax"] else ""
                els.append(
                    html.Div(
                        [
                            html.Span(
                                _MESES_ES[m - 1],
                                style={
                                    "color": _C_MUTED,
                                    "fontSize": "0.59rem",
                                    "minWidth": "22px",
                                },
                            ),
                            html.Span(s["barco"], style={"fontSize": "0.61rem", "color": _C_DARK}),
                            html.Span(pax_txt, style={"fontSize": "0.59rem", "color": _C_MUTED}),
                        ],
                        className="d-flex align-items-center gap-1",
                    )
                )
                if len(els) >= 4:
                    break
            if len(els) >= 4:
                break
        return html.Div(els)

    ships_block = _ship_list(anio_actual)

    leyenda = html.Div([tier_legend, ships_block], className="mb-1")

    has_prev_tier = any(t == "prev" for t in act_tiers)
    nota_fuente = html.Div(
        [
            html.I(className="fas fa-circle-info me-1", style={"fontSize": "0.65rem"}),
            html.Span(
                "Puertos del Estado · estadística oficial mensual"
                + (
                    " · meses sin dato oficial: previsión basada en escalas de crucero del calendario portuario."
                    if has_prev_tier
                    else " · publicado con ~4-6 semanas de retraso."
                ),
            ),
        ],
        style={"fontSize": "0.62rem", "color": _C_MUTED, "marginTop": "4px", "lineHeight": "1.4"},
    )

    _cr_tt_text = tooltip_text
    _cr_tt_id = f"tt-crucero-{re.sub(r'[^a-z0-9]', '-', location_uuid.lower())[:16]}"
    _cr_info_els = (
        [
            html.Span(
                html.I(className="fas fa-info-circle", style={"fontSize": "0.75rem"}),
                id=_cr_tt_id,
                style={
                    "color": "#ced4da",
                    "cursor": "pointer",
                    "display": "inline-flex",
                    "alignItems": "center",
                    "padding": "0 4px",
                },
            ),
            dbc.Tooltip(
                _cr_tt_text,
                target=_cr_tt_id,
                placement="top",
                style={"fontSize": "0.76rem", "maxWidth": "300px", "textAlign": "left"},
            ),
        ]
        if _cr_tt_text
        else []
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
                    *_cr_info_els,
                    kpi_el,
                ],
                className="d-flex align-items-center flex-wrap gap-1 mb-1",
            ),
            leyenda,
            dcc.Graph(
                id=f"crucero-yoy-{location_uuid[:8]}",
                figure=fig,
                config=_CFG_GRAPH,
                style={"height": "230px"},
            ),
            nota_fuente,
        ],
        className="mb-4",
    )


def _render_senal_contexto_modal(
    location_uuid: str, uid: str, fecha_max, ventana: str = "semana", primary_color: str = "#0052CC"
) -> html.Div | None:
    """External signals modal: YoY bar charts per feature + events feed."""
    if not location_uuid:
        return None
    try:
        from src.db.store import get_conn

        conn = get_conn()
        feature_meta = _load_feature_meta(conn, location_uuid)
        desde = fecha_max - timedelta(days=760)
        ts_rows = conn.execute(
            """SELECT e.señal_id, e.fecha::text, e.valor
               FROM valores_señales e
               JOIN activacion_señales f
                 ON f.señal_id = e.señal_id
                AND f.ubicacion_id = e.ubicacion_id
                AND f.status IN ('active', 'contexto')
               WHERE e.ubicacion_id = ? AND e.valor IS NOT NULL AND e.fecha >= ?
               ORDER BY e.señal_id, e.fecha""",
            [location_uuid, str(desde)],
        ).fetchall()
    except Exception:
        return None

    anio_actual = fecha_max.year
    anio_prev = anio_actual - 1

    charts = []
    if ts_rows:
        df_ts = pd.DataFrame(
            ts_rows, columns=["feature_key", "fecha", "value"]
        )  # señal_id→feature_key alias
        df_ts["fecha"] = pd.to_datetime(df_ts["fecha"])
        df_ts["anio"] = df_ts["fecha"].dt.year
        df_ts["mes_num"] = df_ts["fecha"].dt.month

        yoy_keys = [
            k
            for k in df_ts["feature_key"].unique()
            if feature_meta.get(k, {}).get("display_mode") == "yoy"
        ]
        metro_keys = sorted([k for k in yoy_keys if "metro" in k])
        other_keys = sorted([k for k in yoy_keys if k not in metro_keys])

        for fk in metro_keys + other_keys:
            m = feature_meta[fk]
            if "gran_via" in fk:
                station = "Gran Vía: validaciones diarias"
                sub = "Línea 1 (azul) · Línea 5 (verde)"
            elif "callao" in fk:
                station = "Callao: validaciones diarias"
                sub = "Línea 3 (amarilla) · Línea 5 (verde)"
            else:
                station, sub = m["label"], m["sublabel"]
            c = _render_signal_yoy_chart(
                df_ts[df_ts["feature_key"] == fk],
                fk,
                station,
                sub,
                m["color"],
                uid,
                anio_actual,
                anio_prev,
                _MESES_ES,
                m["agg_fn"],
                fecha_max=fecha_max,
                ventana=ventana,
                tooltip_text=m["notas"],
                icon_cls=m["icon_cls"],
                primary_color=primary_color,
            )
            if c:
                charts.append(c)

    # cruceros notas + fallback
    _cr_meta = feature_meta.get("n_pasajeros_crucero_oficial", {})
    cruceros_notas = _cr_meta.get("notas", "")
    cruceros_fallback = _cr_meta.get("fallback_feature_key", "")

    cruceros_section = _render_cruceros_section(
        location_uuid,
        fecha_max,
        ventana,
        cruceros_notas,
        cruceros_fallback,
        primary_color=primary_color,
    )

    if not charts and not cruceros_section:
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
        ]
    )


def _funnel_connector_row(from_z: dict, to_z: dict) -> html.Div:
    """Sentence showing the conversion ratio between two consecutive funnel zones."""
    from_act = from_z["r"].get("visitantes", 0)
    from_ant = from_z["a"].get("visitantes", 0)
    to_act = to_z["r"].get("visitantes", 0)
    to_ant = to_z["a"].get("visitantes", 0)
    if from_act <= 0:
        return html.Div()
    ratio_act = to_act / from_act * 100
    ratio_ant = (to_ant / from_ant * 100) if from_ant > 0 else None
    diff = (ratio_act - ratio_ant) if ratio_ant is not None else None
    txt = (
        f"De los {from_act:,} visitantes de {from_z['zona']}, el {ratio_act:.1f}%"
        f" accedió a {to_z['zona']} ({to_act:,})."
    ).replace(",", ".")
    if diff is not None and abs(diff) >= 0.5:
        sign = "+" if diff >= 0 else ""
        txt += f" {sign}{diff:.1f}pp respecto al período previo."
    return html.P(
        txt,
        className="text-muted mb-0 mt-2",
        style={"fontSize": "0.82rem", "fontStyle": "italic"},
    )


def _render_zona_section_jerarquica(
    zonas_data,
    zona_children_map,
    child_zone_names,
    uid,
    periodo_label,
    primary_color: str = "#0052CC",
) -> html.Div:
    """Zone cards: parent zones first (blue accent), children grouped below each parent."""
    parent_zones = sorted(
        [z for z in zonas_data if z["zona"] not in child_zone_names],
        key=lambda z: _sort_zona_key(z["zona"], z.get("zone_enum")),
    )

    # Lookup table for funnel connector: enum → zone dict (only funnel zones)
    _enum_to_z = {z["zone_enum"]: z for z in zonas_data if z.get("zone_enum") in (0, 1, 2)}
    _next_enum = {2: 1, 1: 0}  # exterior→interior→checkout

    def _connector_after(ze: int | None) -> html.Div:
        """Return a funnel connector if ze has a defined next funnel step."""
        if ze not in _next_enum:
            return html.Div()
        nxt = _next_enum[ze]
        from_z = _enum_to_z.get(ze)
        to_z = _enum_to_z.get(nxt)
        if from_z and to_z:
            return _funnel_connector_row(from_z, to_z)
        return html.Div()

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
                    zone_enum=z.get("zone_enum"),
                    primary_color=primary_color,
                ),
                xs=12,
                sm=6,
                xl=3,
                className="mb-3",
            )
            for z in sorted(zonas_data, key=lambda z: _sort_zona_key(z["zona"], z.get("zone_enum")))
        ]
        return dbc.Row(cols, className="g-3")

    # Root zones with no registered children → render as leaf cards in a flat grid.
    lone_roots = [pz for pz in parent_zones if not zona_children_map.get(pz["zona"])]
    true_parents = [pz for pz in parent_zones if zona_children_map.get(pz["zona"])]

    # Track which funnel step was last rendered to inject connectors between sections.
    _last_funnel_enum: int | None = None

    sections = []
    if lone_roots:
        lone_cols = [
            dbc.Col(
                _render_zona_card(
                    pz["zona"],
                    pz["r"],
                    pz["a"],
                    pz["d"],
                    pz["dias_28"],
                    uid,
                    periodo_label,
                    has_children=False,
                    gap_actual=pz.get("gap_actual", False),
                    gap_anterior=pz.get("gap_anterior", False),
                    zone_enum=pz.get("zone_enum"),
                    primary_color=primary_color,
                ),
                xs=12,
                sm=6,
                className="mb-2",
            )
            for pz in lone_roots
        ]
        sections.append(html.Div(dbc.Row(lone_cols, className="g-2"), className="mb-4"))
        # Track the highest funnel step rendered in lone_roots (exterior = 2 is first)
        lone_enums = [pz.get("zone_enum") for pz in lone_roots if pz.get("zone_enum") in (0, 1, 2)]
        if lone_enums:
            _last_funnel_enum = max(lone_enums)  # 2>1>0, exterior comes first

    for pz in true_parents:
        current_enum = pz.get("zone_enum")
        children_names = zona_children_map.get(pz["zona"], [])
        children_data = [z for z in zonas_data if z["zona"] in children_names]

        # Inject connector between sections when transitioning funnel steps
        if (
            _last_funnel_enum is not None
            and current_enum is not None
            and _next_enum.get(_last_funnel_enum) == current_enum
        ):
            connector = _connector_after(_last_funnel_enum)
            if connector.children:
                sections.append(connector)

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
            zone_enum=pz.get("zone_enum"),
            primary_color=primary_color,
        )

        block = [dbc.Row([dbc.Col(parent_card, xs=12)], className="mb-2 g-2")]

        if children_data:
            # Split children: those with grandchildren act as sub-parents (full-width
            # card + indented grandchildren); simple children go into a grid row.
            simple_cols = []
            sub_parent_blocks = []

            # If this zone (e.g. Tienda) has checkout children, inject ratio before them.
            checkout_children = [cz for cz in children_data if cz.get("zone_enum") == 0]
            pre_children: list = []
            if checkout_children and current_enum == 1:
                conn = _funnel_connector_row(pz, checkout_children[0])
                if conn.children:
                    pre_children.append(conn)

            for cz in sorted(
                children_data, key=lambda z: _sort_zona_key(z["zona"], z.get("zone_enum"))
            ):
                gc_names = zona_children_map.get(cz["zona"], [])
                gc_data = [z for z in zonas_data if z["zona"] in gc_names]
                child_card = _render_zona_card(
                    cz["zona"],
                    cz["r"],
                    cz["a"],
                    cz["d"],
                    cz["dias_28"],
                    uid,
                    periodo_label,
                    has_children=bool(gc_names),
                    gap_actual=cz.get("gap_actual", False),
                    gap_anterior=cz.get("gap_anterior", False),
                    zone_enum=cz.get("zone_enum"),
                    primary_color=primary_color,
                )
                if gc_data:
                    gc_cols = [
                        dbc.Col(
                            _render_zona_card(
                                gz["zona"],
                                gz["r"],
                                gz["a"],
                                gz["d"],
                                gz["dias_28"],
                                uid,
                                periodo_label,
                                has_children=False,
                                gap_actual=gz.get("gap_actual", False),
                                gap_anterior=gz.get("gap_anterior", False),
                                zone_enum=gz.get("zone_enum"),
                                primary_color=primary_color,
                            ),
                            xs=12,
                            sm=6,
                            className="mb-2",
                        )
                        for gz in sorted(
                            gc_data, key=lambda z: _sort_zona_key(z["zona"], z.get("zone_enum"))
                        )
                    ]
                    sub_parent_blocks.append(
                        html.Div(
                            [
                                dbc.Row([dbc.Col(child_card, xs=12)], className="mb-2 g-2"),
                                html.Div(
                                    dbc.Row(gc_cols, className="g-2"),
                                    className="ps-4",
                                    style={
                                        "borderLeft": f"3px solid {_color_zona(cz['zona'])}",
                                        "marginLeft": "8px",
                                    },
                                ),
                            ],
                            className="mb-2",
                        )
                    )
                else:
                    simple_cols.append(dbc.Col(child_card, xs=12, sm=6, className="mb-2"))
            children_content = pre_children
            if simple_cols:
                children_content.append(dbc.Row(simple_cols, className="g-2 mb-2"))
            children_content.extend(sub_parent_blocks)
            block.append(
                html.Div(
                    children_content,
                    className="ps-4",
                    style={
                        "borderLeft": f"3px solid {_color_zona(pz['zona'])}",
                        "marginLeft": "8px",
                    },
                )
            )

        sections.append(html.Div(block, className="mb-4"))
        if current_enum in (0, 1, 2):
            _last_funnel_enum = current_enum

    return html.Div(sections)


def generar_mensajes_salud(
    df,
    ubi,
    zonas_seleccionadas=None,
    location_uuid=None,
    ventana="semana",
    primary_color: str = "#0052CC",
):
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

    _loc = get_location_by_name(ubi)
    lat, lon = (_loc.get("lat", 40.4168), _loc.get("lon", -3.7038)) if _loc else (40.4168, -3.7038)
    clima = _clima_historico(
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

    # ── IDs y enum de zona vía API Aitanna ──────────────────────────────
    # Aitanna: zone_enum=2 → exterior/calle, 1 → interior, 0 → checkout, 3 → subzonas.
    _ext_zona_ids: set[str] = set()
    zona_enum_map: dict[str, int] = {}  # {zona_name → zone_enum}
    if location_uuid:
        try:
            from src.db.store import get_conn as _gc2

            _rows = (
                _gc2()
                .execute(
                    "SELECT zona_id, nombre, zone_enum FROM zonas WHERE ubicacion_id = ? AND zone_enum IS NOT NULL",
                    [location_uuid],
                )
                .fetchall()
            )
            for _zid, _zname, _zenum in _rows:
                zona_enum_map[_zname] = _zenum
                if _zenum == 2:
                    _ext_zona_ids.add(_zid)
        except Exception:
            pass

    # df filtrado a zona exterior (sin doble conteo) para gráficos de patrones
    df_ext = (
        df[df["zona_id"].isin(_ext_zona_ids)] if _ext_zona_ids and "zona_id" in df.columns else df
    )

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
                zone_enum=zona_enum_map.get(zona),
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

    # ── Geo data ─────────────────────────────────────────────────────────
    geo_vals_loc = get_geo_vals(location_uuid) if location_uuid else {}
    fecha_captura = get_geo_snapshot_date(location_uuid) if location_uuid else None

    # ── Header ───────────────────────────────────────────────────────────
    _hero_img = _find_hero_image(location_uuid)
    _rgb = _rgb_str(primary_color)
    _rgb_dk = _rgb_str(_darken(primary_color))
    if _hero_img:
        # Gradiente cinematográfico: color de marca arriba-izquierda → transparente
        # en el centro → oscuro abajo donde vive el texto.
        _header_bg = {
            "backgroundImage": (
                f"linear-gradient(160deg, rgba({_rgb},0.62) 0%, rgba(0,0,0,0.08) 45%, rgba(0,0,0,0.74) 100%), "
                f"url('{_hero_img}')"
            ),
            "backgroundSize": "cover",
            "backgroundPosition": "center",
        }
    else:
        _header_bg = {
            "background": f"linear-gradient(135deg, {primary_color} 0%, {_darken(primary_color)} 100%)"
        }
    _txt_shadow = "0 1px 4px rgba(0,0,0,0.55)" if _hero_img else "none"
    header = dbc.Card(
        dbc.CardBody(
            html.Div(
                [
                    html.P(
                        "ESTADO",
                        className="mb-1 text-uppercase fw-bold",
                        style={
                            "fontSize": "0.6rem",
                            "letterSpacing": "1.5px",
                            "color": "rgba(255,255,255,0.72)",
                            "textShadow": _txt_shadow,
                        },
                    ),
                    html.H3(
                        ubi,
                        className="fw-bold mb-1",
                        style={
                            "color": "white",
                            "fontSize": "1.45rem",
                            "textShadow": "0 2px 10px rgba(0,0,0,0.60)" if _hero_img else "none",
                        },
                    ),
                    html.P(
                        f"{(fecha_max - timedelta(days=dias_v - 1)).strftime('%d %b')} – "
                        f"{fecha_max.strftime('%d %b %Y')}",
                        className="mb-0",
                        style={
                            "fontSize": "0.82rem",
                            "color": "rgba(255,255,255,0.85)",
                            "fontWeight": "500",
                            "textShadow": _txt_shadow,
                        },
                    ),
                ],
                style={"marginTop": "auto"},
            ),
            style={
                "display": "flex",
                "flexDirection": "column",
                "padding": "20px 24px",
                "minHeight": "175px",
            },
        ),
        className="border-0 rounded-4 mb-4 shadow",
        style=_header_bg,
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
                zonas_data,
                zona_children_map,
                child_zone_names,
                uid,
                periodo_label,
                primary_color=primary_color,
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
                df_ext,
                zonas_data,
                fecha_max,
                uid,
                ventana=ventana,
                child_zones=child_zone_names,
                clima=clima,
                primary_color=primary_color,
            ),
        ]
    )

    sec_senales = _render_senal_contexto_modal(
        location_uuid, uid, fecha_max, ventana, primary_color=primary_color
    ) or html.Div(html.P("Sin datos de contexto externo disponibles.", className="text-muted"))

    mapa_contexto = generar_mapa_contexto(location_uuid, geo_vals_loc) if location_uuid else None
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
                    "fas fa-layer-group", f"Estado por zona  {_ventana_zona_lbl}", primary_color
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
        active_item=["zona"],
        className="pm-acordeon shadow-sm rounded-4",
    )

    _correlacion_card = render_informe_tabs(
        location_uuid, zonas_data, df, fmin_p, fecha_max, ventana=ventana
    )
    _calendario_card = render_periodo_calendar(location_uuid, fmin_p, fecha_max)

    cuerpo_superior = (
        dbc.Row(
            [
                dbc.Col(_correlacion_card, xs=12, lg=6, className="mb-3 mb-lg-0"),
                dbc.Col(
                    [_calendario_card, html.Div(className="mb-3"), mapa_contexto],
                    xs=12,
                    lg=6,
                ),
            ],
            className="mb-3 align-items-start",
        )
        if mapa_contexto
        else dbc.Row(
            [
                dbc.Col(_correlacion_card, xs=12, lg=6, className="mb-3 mb-lg-0"),
                dbc.Col(_calendario_card, xs=12, lg=6),
            ],
            className="mb-3 align-items-start",
        )
    )

    return html.Div(
        [
            pdf_header,
            header,
            cuerpo_superior,
            acordeon,
        ]
    )


def generar_panel_pm(df_completo, locs, zonas_sel, ventana="semana"):
    if df_completo is None or df_completo.empty:
        return dbc.Alert("Sincroniza los datos.", color="warning", className="rounded-4")
    if not locs:
        return dbc.Alert("Selecciona una ubicación.", color="info", className="rounded-4")

    from src.core.org_branding import get_branding_from_locs

    primary_color = get_branding_from_locs(locs).primary

    paneles = []
    for ubi in df_completo[df_completo["location_id"].isin(locs)]["Ubicación"].unique():
        df_ubi = df_completo[df_completo["Ubicación"] == ubi]
        loc_uuid = df_ubi["location_id"].iloc[0] if "location_id" in df_ubi.columns else None
        paneles.append(
            generar_mensajes_salud(
                df_ubi, ubi, zonas_sel, loc_uuid, ventana=ventana, primary_color=primary_color
            )
        )
    return html.Div(paneles)
