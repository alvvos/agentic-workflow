"""
Panel geoespacial Esri — Panel PM.
Responde a: ¿Qué potencial tiene esta ubicación y a qué competencia se enfrenta?

Secciones (todas auto-generadas desde geo_features.json):
  A. Alcance peatonal  — captación isócrona, mapa, pirámide de edad, estructura de hogar
  B. Capacidad económica — renta, salud financiera, gasto por categoría
  C. Comportamiento digital — canal online, presión omnicanal
  D. Entorno competitivo — transporte, competidores, movilidad (Phase 2)
"""

import base64
import json
import math
import random

import dash_bootstrap_components as dbc
import dash_leaflet as dl
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_extensions.javascript import assign

from src.core.theme import (
    C_AMBER as _C_AMBER,
)
from src.core.theme import (
    C_DANGER as _C_RED,
)
from src.core.theme import (
    C_DARK as _C_DARK,
)
from src.core.theme import (
    C_GRID as _C_GRID,
)
from src.core.theme import (
    C_MUTED as _C_MUTED,
)
from src.core.theme import (
    C_PRIMARY as _C_PRIMARY,
)
from src.core.theme import (
    C_SUCCESS as _C_GREEN,
)
from src.core.theme import (
    CFG_GRAPH as _CFG,
)
from src.core.utils import MESES_ES as _MESES_ES_GEO
from src.data_processing.geo_enrichment import get_catchment_rings

# ── JS para pines y clusters Leaflet (módulo-nivel — no recrear en callbacks) ──
_JS_POINT_TO_LAYER = assign(
    """function(feature, latlng, ctx) {
    const c = feature.properties.color || '#3388ff';
    const icon = L.divIcon({
        className: '',
        html: '<svg width="22" height="32" viewBox="0 0 22 32" xmlns="http://www.w3.org/2000/svg">' +
              '<path d="M11 0C4.9 0 0 4.9 0 11c0 8.3 11 21 11 21s11-12.7 11-21C22 4.9 17.1 0 11 0z"' +
              ' fill="' + c + '" stroke="white" stroke-width="1.5"/>' +
              '<circle cx="11" cy="11" r="4.5" fill="white" opacity="0.75"/></svg>',
        iconSize: [22, 32], iconAnchor: [11, 32], popupAnchor: [0, -34]
    });
    return L.marker(latlng, {icon}).bindTooltip(
        '<b>' + feature.properties.name + '</b>' +
        (feature.properties.detalle ? '<br>' + feature.properties.detalle : ''),
        {direction: 'top', offset: [0, -30]}
    );
}"""
)

_JS_CLUSTER_TO_LAYER = assign(
    """function(feature, latlng, index, ctx) {
    const count = feature.properties.point_count;
    const c = (ctx.props.hideout && ctx.props.hideout.color) ? ctx.props.hideout.color : '#3388ff';
    const label = count > 9 ? '+' + count : String(count);
    const icon = L.divIcon({
        className: '',
        html: '<div style="background:' + c + ';color:white;border-radius:50%;width:32px;' +
              'height:32px;display:flex;align-items:center;justify-content:center;' +
              'font-weight:700;font-size:12px;border:2px solid white;' +
              'box-shadow:0 2px 6px rgba(0,0,0,.3)">' + label + '</div>',
        iconSize: [32, 32], iconAnchor: [16, 16]
    });
    return L.marker(latlng, {icon});
}"""
)

# Metro de Madrid — logo simplificado (rombo rojo con M blanca)
_METRO_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    b'<polygon points="50,2 98,50 50,98 2,50" fill="#DA0000"/>'
    b'<text x="50" y="72" text-anchor="middle" fill="white" '
    b'font-size="52" font-weight="900" font-family="Arial Black,Arial">M</text>'
    b"</svg>"
)
_METRO_LOGO_SRC = "data:image/svg+xml;base64," + base64.b64encode(_METRO_SVG).decode()

# ── Señales externas de área ──────────────────────────────────────────────────
# El contexto espacial (POIs) y los metadatos visuales por categoría (label,
# color, icono) viven en location_pois y poi_category_registry.  Ver _get_pois
# y _load_geo_meta más abajo.


_UNIVERSAL_EXT_KEYS = frozenset(
    {
        "ev_festivo_regional",
        "ev_rank_municipal",
        "ev_rank_total",
        "ev_vacaciones_escolares",
        "llueve",
        "temp_max",
        "temp_min",
    }
)
_EV_RANK_KEYS = ["ev_rank_deportivo", "ev_rank_concierto", "ev_rank_festival"]
_IMP_COLOR = {"alto": "#c0392b", "medio": "#d68910", "bajo": "#27ae60"}


def _load_poi_cat_meta() -> dict:
    """Atajo: devuelve solo poi_cat_meta con una conexión interna."""
    try:
        from src.db.store import get_conn

        _, poi_cat_meta, _ = _load_geo_meta(get_conn())
        return poi_cat_meta
    except Exception:
        return {}


def _load_geo_meta(conn) -> tuple[dict, dict, dict]:
    """
    Devuelve (feature_meta, poi_cat_meta, norm_tipo).

    feature_meta: {feature_key: {label, icon_cls, color, agg_fn, canonical_type}}
    poi_cat_meta: {category:    {label, icon_cls, color, badge_color}}
    norm_tipo:    {raw_key:     canonical_type}  — derivado de
                  feature_registry.canonical_type para mapear eventos raw a
                  tipos canónicos del calendario.
    """
    feature_meta: dict = {}
    poi_cat_meta: dict = {}
    norm_tipo: dict = {}
    try:
        rows = conn.execute(
            "SELECT feature_key, label, icon_cls, color, agg_fn, canonical_type "
            "FROM feature_registry WHERE label IS NOT NULL"
        ).fetchall()
        for fk, lbl, icon, col, agg, canon in rows:
            feature_meta[fk] = {
                "label": lbl or fk,
                "icon_cls": icon or "fas fa-satellite-dish",
                "color": col or "#0052CC",
                "agg_fn": agg or "sum",
            }
            if canon:
                norm_tipo[fk] = canon
        cat_rows = conn.execute(
            "SELECT category, label, icon_cls, color, badge_color FROM poi_category_registry"
        ).fetchall()
        poi_cat_meta = {
            cat: {
                "label": lbl,
                "icon_cls": icon or "fas fa-map-pin",
                "color": col or "#6c757d",
                "badge_color": bc or "secondary",
            }
            for cat, lbl, icon, col, bc in cat_rows
        }
    except Exception:
        pass
    return feature_meta, poi_cat_meta, norm_tipo


def _render_area_signals(location_uuid: str):
    """
    Sección 'Señales del área': gráfico metro por estación + gráfico turistas +
    feed de eventos recientes y próximos (sin emojis, iconos FA).
    Devuelve None si no hay datos.
    """
    from datetime import date, timedelta

    hoy = date.today()

    cruise_fc_rows: list = []
    feature_meta: dict = {}
    poi_cat_meta: dict = {}
    try:
        from src.db.store import get_conn

        conn = get_conn()
        feature_meta, poi_cat_meta, _ = _load_geo_meta(conn)
        ts_rows = conn.execute(
            """SELECT feature_key, fecha::text, value
               FROM   store_features_ext
               WHERE  location_uuid = ? AND value IS NOT NULL AND fecha >= ?
               ORDER  BY feature_key, fecha""",
            [location_uuid, str(hoy - timedelta(days=182))],
        ).fetchall()
        # Escalas futuras para el gráfico de previsión (próximos 2 meses)
        cruise_fc_rows = conn.execute(
            """SELECT DATE_TRUNC('month', fecha_inicio::date)::text,
                      COALESCE(SUM(
                          CASE WHEN (metadata->>'n_pasajeros') ~ '^[0-9]+$'
                               THEN (metadata->>'n_pasajeros')::int ELSE 0 END
                      ), 0)
               FROM   store_calendario_org
               WHERE  location_uuid = ?
                 AND  evento_key = 'escala_crucero'
                 AND  fecha_inicio > CURRENT_DATE
                 AND  fecha_inicio <= (CURRENT_DATE + INTERVAL '2 months')::date
               GROUP  BY 1 ORDER BY 1""",
            [location_uuid],
        ).fetchall()
        ev_rows = conn.execute(
            """SELECT evento_key, fecha_inicio::text, fecha_fin::text, metadata
               FROM   store_calendario_org
               WHERE  location_uuid = ?
                 AND  fecha_inicio >= ? AND fecha_inicio <= ?
               ORDER  BY fecha_inicio""",
            [location_uuid, str(hoy - timedelta(days=90)), str(hoy + timedelta(days=90))],
        ).fetchall()
    except Exception:
        return None

    notas_map: dict[str, str] = {}
    try:
        all_keys = list(
            {r[0] for r in ts_rows}
            | set(_EV_RANK_KEYS)
            | {"afluencia_metro_gran_via", "afluencia_metro_callao", "n_pasajeros_crucero_oficial"}
        )
        notas_map = {
            fk: notas
            for fk, notas in conn.execute(
                "SELECT feature_key, notas FROM feature_registry "
                "WHERE feature_key = ANY(?) AND notas IS NOT NULL",
                [all_keys],
            ).fetchall()
        }
    except Exception:
        pass

    ts_rows = [r for r in ts_rows if r[0] not in _UNIVERSAL_EXT_KEYS]
    # Eventos raw: feature_registry con display_mode='raw' (categoría eventos/cruceros).
    try:
        _raw_keys = {
            r[0]
            for r in conn.execute(
                "SELECT feature_key FROM feature_registry WHERE display_mode = 'raw'"
            ).fetchall()
        }
    except Exception:
        _raw_keys = set()
    ev_rows = [r for r in ev_rows if r[0] in _raw_keys]

    if not ts_rows and not ev_rows:
        return None

    _METRO_KEYS = ["afluencia_metro_gran_via", "afluencia_metro_callao"]
    _TOURIST_KEYS = ["n_turistas_isocrona", "n_pasajeros_crucero_dia"]

    # ── Gráfico metro (agrupado por estación) ─────────────────────────────────
    metro_chart_col = None
    metro_keys_present = [k for k in _METRO_KEYS if any(r[0] == k for r in ts_rows)]
    if metro_keys_present:
        df_m = pd.DataFrame(ts_rows, columns=["fk", "fecha", "value"])
        df_m["fecha"] = pd.to_datetime(df_m["fecha"])
        df_m["mes"] = df_m["fecha"].dt.to_period("M").dt.to_timestamp()

        fig_m = go.Figure()
        for fk in metro_keys_present:
            _meta = feature_meta.get(fk, {})
            label = _meta.get("label", fk)
            color = _meta.get("color", "#0052CC")
            sub = (
                df_m[df_m["fk"] == fk]
                .groupby("mes")["value"]
                .mean()
                .reset_index()
                .sort_values("mes")
            )
            m_lbls = [f"{_MESES_ES_GEO[r.month-1]}" for r in sub["mes"].dt.date]
            m_vals = sub["value"].tolist()
            # Texto interior blanco para barra azul, oscuro para barra amarilla
            txt_color = "white" if color.startswith("#0") else "#333"
            fig_m.add_trace(
                go.Bar(
                    x=m_lbls,
                    y=m_vals,
                    name=label,
                    marker_color=color,
                    opacity=0.90,
                    text=[f"{int(v/1000):.0f}k" for v in m_vals],
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont=dict(size=8, color=txt_color, family="Arial, sans-serif"),
                )
            )

        # Marcas verticales de eventos de alto impacto
        for ekey, fi, ff, meta_raw in ev_rows:
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else {}
            except Exception:
                meta = {}
            if meta.get("impacto") != "alto":
                continue
            fi_dt = pd.to_datetime(fi)
            mes_lbl = _MESES_ES_GEO[fi_dt.month - 1]
            titulo = meta.get("titulo", ekey)[:30]
            fig_m.add_annotation(
                x=mes_lbl,
                y=1.0,
                yref="paper",
                text="▲",
                showarrow=False,
                font=dict(size=9, color=feature_meta.get(ekey, {}).get("color", "#888")),
                hovertext=f"<b>{titulo}</b><br>{fi_dt.strftime('%-d %b %Y')}"
                + (f"<br>{meta.get('asistentes','')} asistentes" if meta.get("asistentes") else ""),
                hoverlabel=dict(
                    bgcolor="white",
                    bordercolor=feature_meta.get(ekey, {}).get("color", "#888"),
                    font=dict(size=10),
                ),
                xanchor="center",
                yanchor="bottom",
                yshift=3,
            )

        fig_m.update_layout(
            barmode="group",
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(t=28, b=4, l=4, r=4),
            height=200,
            legend=dict(
                orientation="h",
                x=1,
                xanchor="right",
                y=1.10,
                font=dict(size=10, color=_C_DARK),
                bgcolor="rgba(0,0,0,0)",
            ),
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color="#8c9199")),
            yaxis=dict(visible=False, showgrid=True, gridcolor="#f0f0f0"),
        )

        _tt_metro_id = f"tt-metro-{location_uuid[:8]}"
        metro_chart_col = dbc.Col(
            [
                html.Div(
                    [
                        html.Img(
                            src=_METRO_LOGO_SRC,
                            height=16,
                            style={"verticalAlign": "middle", "marginRight": "6px"},
                        ),
                        html.Span(
                            "Validaciones diarias por estación · media mensual",
                            style={
                                "fontSize": "0.66rem",
                                "color": _C_MUTED,
                                "textTransform": "uppercase",
                                "letterSpacing": "0.45px",
                                "fontWeight": "600",
                            },
                        ),
                        html.I(
                            id=_tt_metro_id,
                            className="fas fa-info-circle ms-2",
                            style={"color": "#ced4da", "fontSize": "0.72rem", "cursor": "pointer"},
                        ),
                        dbc.Tooltip(
                            notas_map.get(
                                metro_keys_present[0],
                                "Validaciones diarias de tarjeta metro por estación. Fuente: Metro de Madrid.",
                            ),
                            target=_tt_metro_id,
                            placement="right",
                            style={"fontSize": "0.76rem", "maxWidth": "300px"},
                        ),
                    ],
                    className="d-flex align-items-center mb-2",
                ),
                dcc.Graph(
                    id=f"ext-metro-{location_uuid[:8]}",
                    figure=fig_m,
                    config=_CFG,
                    style={"height": "200px"},
                ),
            ],
            xs=12,
            lg=7,
        )

    # ── Gráfico turistas / cruceros ───────────────────────────────────────────
    # Cruceros: 3 niveles de color según fiabilidad del dato.
    # Fuente confirmada (store_features_ext, fecha < inicio mes actual): #1abc9c
    # Mes en curso (datos acumulados hasta hoy, aún incompleto):         #82d9cd
    # Previsión próximos 2 meses (store_calendario_org, fecha > hoy):    #c5ede9
    _C_CRUISE_CONF = "#1abc9c"
    _C_CRUISE_PROG = "#82d9cd"
    _C_CRUISE_PREV = "#c5ede9"
    _MES_ACTUAL_START = date(hoy.year, hoy.month, 1)

    tourist_chart_col = None
    tourist_keys_present = [k for k in _TOURIST_KEYS if any(r[0] == k for r in ts_rows)]
    has_cruise = "n_pasajeros_crucero_dia" in tourist_keys_present
    if tourist_keys_present or (has_cruise and cruise_fc_rows):
        df_t = pd.DataFrame(ts_rows, columns=["fk", "fecha", "value"])
        df_t["fecha"] = pd.to_datetime(df_t["fecha"])
        df_t["mes"] = df_t["fecha"].dt.to_period("M").dt.to_timestamp()

        fig_t = go.Figure()
        for fk in tourist_keys_present:
            _meta = feature_meta.get(fk, {})
            label = _meta.get("label", fk)
            agg_fn = _meta.get("agg_fn", "sum")
            color = _meta.get("color", "#0052CC")
            sub = (
                df_t[df_t["fk"] == fk]
                .groupby("mes")["value"]
                .agg(agg_fn)
                .reset_index()
                .sort_values("mes")
            )
            if sub.empty:
                continue

            if fk == "n_pasajeros_crucero_dia":
                # Barras con color por nivel de fiabilidad
                bars = [
                    {
                        "lbl": _MESES_ES_GEO[row["mes"].month - 1],
                        "val": row["value"],
                        "tipo": "prog" if row["mes"].date() >= _MES_ACTUAL_START else "conf",
                    }
                    for _, row in sub.iterrows()
                ]
                # Meses de previsión desde store_calendario_org
                meses_ya_en_bars = {b["lbl"] for b in bars}
                for mes_str, pax in cruise_fc_rows:
                    lbl = _MESES_ES_GEO[pd.to_datetime(mes_str).month - 1]
                    if lbl not in meses_ya_en_bars:
                        bars.append({"lbl": lbl, "val": float(pax), "tipo": "prev"})
                        meses_ya_en_bars.add(lbl)

                _cmap = {"conf": _C_CRUISE_CONF, "prog": _C_CRUISE_PROG, "prev": _C_CRUISE_PREV}
                _txtmap = {"conf": "white", "prog": "white", "prev": "#4a9e96"}
                _hvmap = {"conf": "Real", "prog": "En curso", "prev": "Previsión"}
                fig_t.add_trace(
                    go.Bar(
                        x=[b["lbl"] for b in bars],
                        y=[b["val"] for b in bars],
                        name=label,
                        marker_color=[_cmap[b["tipo"]] for b in bars],
                        opacity=0.88,
                        text=[
                            f"{int(b['val']/1000):.1f}k" if b["val"] >= 1000 else str(int(b["val"]))
                            for b in bars
                        ],
                        textposition="inside",
                        insidetextanchor="middle",
                        textfont=dict(
                            size=8,
                            color=[_txtmap[b["tipo"]] for b in bars],
                            family="Arial, sans-serif",
                        ),
                        customdata=[_hvmap[b["tipo"]] for b in bars],
                        hovertemplate="<b>%{x}</b>: %{y:,.0f} pax<br><i>%{customdata}</i><extra></extra>",
                    )
                )
            else:
                m_lbls = [_MESES_ES_GEO[r.month - 1] for r in sub["mes"].dt.date]
                m_vals = sub["value"].tolist()
                fig_t.add_trace(
                    go.Bar(
                        x=m_lbls,
                        y=m_vals,
                        name=label,
                        marker_color=color,
                        opacity=0.88,
                        text=[f"{int(v/1000):.1f}k" if v >= 1000 else str(int(v)) for v in m_vals],
                        textposition="inside",
                        insidetextanchor="middle",
                        textfont=dict(size=8, color="white", family="Arial, sans-serif"),
                    )
                )

        fig_t.update_layout(
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
            margin=dict(t=28, b=4, l=4, r=4),
            height=200,
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color="#8c9199")),
            yaxis=dict(visible=False, showgrid=True, gridcolor="#f0f0f0"),
        )
        only_cruise = has_cruise and not any(
            k == "n_turistas_isocrona" for k in tourist_keys_present
        )
        subtitle_icon = "fas fa-ship me-2" if only_cruise else "fas fa-user-friends me-2"
        subtitle_color = "#16a085" if only_cruise else "#e67e22"

        # Leyenda de colores inline solo si hay cruceros
        legend_nodes = []
        if has_cruise:
            for lbl, col in [
                ("Real", _C_CRUISE_CONF),
                ("En curso", _C_CRUISE_PROG),
                ("Previsión", _C_CRUISE_PREV),
            ]:
                legend_nodes += [
                    html.Span("■ ", style={"color": col, "fontSize": "0.7rem"}),
                    html.Span(
                        lbl + "  ",
                        style={"fontSize": "0.62rem", "color": _C_MUTED, "marginRight": "6px"},
                    ),
                ]

        tourist_chart_col = dbc.Col(
            [
                html.Div(
                    [
                        html.I(
                            className=f"{subtitle_icon}",
                            style={"color": subtitle_color, "fontSize": "0.75rem"},
                        ),
                        html.Span(
                            (
                                "Pasajeros crucero · suma mensual"
                                if has_cruise and len(tourist_keys_present) == 1
                                else "Turistas estimados · zona 0-15 min · media mensual"
                            ),
                            style={
                                "fontSize": "0.66rem",
                                "color": _C_MUTED,
                                "textTransform": "uppercase",
                                "letterSpacing": "0.45px",
                                "fontWeight": "600",
                            },
                        ),
                        *(
                            [html.Span("  ·  ", style={"color": _C_MUTED, "fontSize": "0.66rem"})]
                            + legend_nodes
                            if legend_nodes
                            else []
                        ),
                        html.I(
                            id=f"tt-tour-{location_uuid[:8]}",
                            className="fas fa-info-circle ms-2",
                            style={"color": "#ced4da", "fontSize": "0.72rem", "cursor": "pointer"},
                        ),
                        dbc.Tooltip(
                            notas_map.get(
                                (
                                    "n_pasajeros_crucero_oficial"
                                    if has_cruise and len(tourist_keys_present) == 1
                                    else tourist_keys_present[0]
                                ),
                                "",
                            ),
                            target=f"tt-tour-{location_uuid[:8]}",
                            placement="left",
                            style={"fontSize": "0.76rem", "maxWidth": "300px"},
                        ),
                    ],
                    className="d-flex align-items-center mb-2 flex-wrap",
                ),
                dcc.Graph(
                    id=f"ext-tour-{location_uuid[:8]}",
                    figure=fig_t,
                    config=_CFG,
                    style={"height": "200px"},
                ),
            ],
            xs=12,
            lg=5,
        )

    chart_cols = [c for c in [metro_chart_col, tourist_chart_col] if c is not None]
    chart_row = dbc.Row(chart_cols, className="g-3 mb-3") if chart_cols else None

    # ── Gráfico ev_rank (deportivo / concierto / festival) ────────────────────
    ev_rank_row = None
    ev_rank_keys_present = [k for k in _EV_RANK_KEYS if any(r[0] == k for r in ts_rows)]
    if ev_rank_keys_present:
        df_ev = pd.DataFrame(ts_rows, columns=["fk", "fecha", "value"])
        df_ev["fecha"] = pd.to_datetime(df_ev["fecha"])
        df_ev["mes"] = df_ev["fecha"].dt.to_period("M").dt.to_timestamp()
        fig_ev = go.Figure()
        for fk in ev_rank_keys_present:
            _meta = feature_meta.get(fk, {})
            label = _meta.get("label", fk)
            color = _meta.get("color", "#0052CC")
            sub = (
                df_ev[df_ev["fk"] == fk]
                .groupby("mes")["value"]
                .max()
                .reset_index()
                .sort_values("mes")
            )
            if sub.empty:
                continue
            m_lbls = [_MESES_ES_GEO[r.month - 1] for r in sub["mes"].dt.date]
            fig_ev.add_trace(
                go.Bar(
                    x=m_lbls,
                    y=sub["value"].tolist(),
                    name=label,
                    marker_color=color,
                    opacity=0.85,
                )
            )
        fig_ev.update_layout(
            barmode="group",
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(t=28, b=4, l=4, r=4),
            height=180,
            legend=dict(
                orientation="h",
                x=1,
                xanchor="right",
                y=1.12,
                font=dict(size=10, color=_C_DARK),
                bgcolor="rgba(0,0,0,0)",
            ),
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color="#8c9199")),
            yaxis=dict(visible=False, range=[0, 110], showgrid=True, gridcolor="#f0f0f0"),
        )
        _tt_evrank_id = f"tt-evrank-{location_uuid[:8]}"
        ev_rank_row = dbc.Row(
            dbc.Col(
                [
                    html.Div(
                        [
                            html.I(
                                className="fas fa-ticket-alt me-2",
                                style={"color": "#8e44ad", "fontSize": "0.72rem"},
                            ),
                            html.Span(
                                "Ranking de eventos · pico mensual (0 – 100)",
                                style={
                                    "fontSize": "0.66rem",
                                    "color": _C_MUTED,
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.45px",
                                    "fontWeight": "600",
                                },
                            ),
                            html.I(
                                id=_tt_evrank_id,
                                className="fas fa-info-circle ms-2",
                                style={
                                    "color": "#ced4da",
                                    "fontSize": "0.72rem",
                                    "cursor": "pointer",
                                },
                            ),
                            dbc.Tooltip(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                f"{feature_meta.get(fk, {}).get('label', fk)}: ",
                                                style={"fontWeight": "600"},
                                            ),
                                            html.Span(notas_map.get(fk, "")),
                                        ],
                                        className="mb-1",
                                    )
                                    for fk in ev_rank_keys_present
                                    if notas_map.get(fk)
                                ],
                                target=_tt_evrank_id,
                                placement="right",
                                style={"fontSize": "0.76rem", "maxWidth": "340px"},
                            ),
                        ],
                        className="d-flex align-items-center mb-2",
                    ),
                    dcc.Graph(
                        id=f"ext-evrank-{location_uuid[:8]}",
                        figure=fig_ev,
                        config=_CFG,
                        style={"height": "180px"},
                    ),
                ],
                xs=12,
            ),
            className="g-3 mb-4",
        )

    # ── Feed de eventos ───────────────────────────────────────────────────────
    pasados = [(ek, fi, ff, m) for ek, fi, ff, m in ev_rows if fi <= str(hoy)]
    proximos = [(ek, fi, ff, m) for ek, fi, ff, m in ev_rows if fi > str(hoy)]

    def _ev_item(ekey, fi, meta_raw):
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except Exception:
            meta = {}
        fi_dt = pd.to_datetime(fi)
        _ev_meta = feature_meta.get(ekey, {})
        icon_fa = meta.get("icono_fa") or _ev_meta.get("icon_cls", "fas fa-calendar")
        titulo = meta.get("titulo", ekey)
        desc = meta.get("descripcion", "")
        imp = meta.get("impacto", "")
        asist = meta.get("asistentes", "")
        cat_lbl = _ev_meta.get("label", ekey)
        c_brd = _ev_meta.get("color", "#adb5bd")
        c_imp = _IMP_COLOR.get(imp, "#adb5bd")

        return html.Div(
            [
                html.Div(
                    [
                        html.I(
                            className=f"{icon_fa} me-2 flex-shrink-0",
                            style={
                                "color": c_brd,
                                "fontSize": "0.78rem",
                                "marginTop": "2px",
                                "width": "14px",
                                "textAlign": "center",
                            },
                        ),
                        html.Span(
                            titulo,
                            className="fw-semibold",
                            style={"fontSize": "0.82rem", "color": _C_DARK, "lineHeight": "1.3"},
                        ),
                    ],
                    className="d-flex align-items-start mb-1",
                ),
                html.Div(
                    [
                        dbc.Badge(
                            cat_lbl,
                            color="light",
                            style={
                                "color": c_brd,
                                "border": f"1px solid {c_brd}",
                                "fontSize": "0.61rem",
                                "fontWeight": "600",
                            },
                            className="me-1 px-2 py-0",
                        ),
                        html.Span(
                            fi_dt.strftime("%-d %b %Y"),
                            className="text-muted me-2",
                            style={"fontSize": "0.70rem"},
                        ),
                        (
                            html.Span(
                                f"{asist} asistentes",
                                className="text-muted",
                                style={"fontSize": "0.68rem"},
                            )
                            if asist
                            else html.Span()
                        ),
                    ],
                    className="d-flex align-items-center flex-wrap gap-1 mb-1",
                ),
                (
                    html.P(
                        desc[:170] + ("…" if len(desc) > 170 else ""),
                        className="text-muted mb-1",
                        style={"fontSize": "0.71rem", "lineHeight": "1.4"},
                    )
                    if desc
                    else html.Div()
                ),
                (
                    dbc.Badge(
                        f"Impacto {imp}",
                        pill=True,
                        style={"backgroundColor": c_imp, "fontSize": "0.58rem"},
                        className="mt-0",
                    )
                    if imp
                    else html.Div()
                ),
            ],
            className="pb-3 mb-2",
            style={
                "borderBottom": "1px solid #ebebeb",
                "borderLeft": f"3px solid {c_brd}",
                "paddingLeft": "10px",
            },
        )

    def _feed_col(title, icon_cls, items, limit=4, newest_first=False):
        items_shown = list(reversed(items[-limit:])) if newest_first else items[:limit]
        empty = html.P(
            "Sin eventos en este período.", className="text-muted", style={"fontSize": "0.76rem"}
        )
        return dbc.Col(
            [
                html.Div(
                    [
                        html.I(
                            className=f"{icon_cls} me-1",
                            style={"color": _C_MUTED, "fontSize": "0.68rem"},
                        ),
                        html.Span(
                            title,
                            style={
                                "fontSize": "0.65rem",
                                "color": _C_MUTED,
                                "textTransform": "uppercase",
                                "letterSpacing": "0.6px",
                                "fontWeight": "700",
                            },
                        ),
                    ],
                    className="d-flex align-items-center border-bottom pb-2 mb-3",
                ),
                (
                    html.Div([_ev_item(ek, fi, m) for ek, fi, ff, m in items_shown])
                    if items_shown
                    else empty
                ),
            ],
            xs=12,
            md=6,
        )

    feed_row = dbc.Row(
        [
            _feed_col("Eventos recientes", "fas fa-history", pasados, newest_first=True),
            _feed_col("Próximos eventos", "fas fa-calendar-check", proximos, newest_first=False),
        ],
        className="g-4",
    )

    # ── Ensamblar ─────────────────────────────────────────────────────────────
    children = []
    if chart_row:
        children.append(chart_row)
    if ev_rank_row:
        children.append(ev_rank_row)
    children.append(feed_row)

    return html.Div(
        [
            html.Div(
                [
                    html.I(
                        className="fas fa-broadcast-tower me-2",
                        style={"color": "#17a2b8", "fontSize": "0.88rem"},
                    ),
                    html.Span(
                        "Señales del área",
                        className="fw-bold text-dark",
                        style={"fontSize": "0.92rem"},
                    ),
                ],
                className="d-flex align-items-center border-bottom pb-2 mb-4 mt-1",
            ),
            html.Div(children),
        ],
        className="mb-3",
    )


_C_TEAL = "#17a2b8"
_C_PURPLE = "#8e44ad"

_FONT = dict(family="Arial, sans-serif")
# _CFG ya importado de src.core.theme al principio del módulo.
_H_CHART = "400px"
_H_MID = "340px"
_H_SM = "280px"

_REF_RENTA = 25_000
_REF_GASTO_ROPA = 1_200


# ─────────────────────────────────────────────────────────────────────────────
# Helpers genéricos
# ─────────────────────────────────────────────────────────────────────────────


def _norm(val, lo, hi):
    if val is None:
        return 0.0
    return max(0.0, min(1.0, (val - lo) / (hi - lo)))


def _pct_of(num, denom):
    """Safe percentage: num/denom*100, or None if inputs invalid."""
    if num is None or not denom:
        return None
    return num / denom * 100


def _fmt_pct(v, decimals=0):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _fmt_eur(v, decimals=0):
    if v is None:
        return "—"
    if v >= 1_000:
        return f"{v:,.{decimals}f} €"
    return f"{v:.{decimals}f} €"


def _info_ubicacion(uuid):
    try:
        from src.db.queries import get_location_by_uuid

        loc = get_location_by_uuid(uuid)
        if loc:
            return loc["name"], loc.get("lat"), loc.get("lon")
    except Exception:
        pass
    return uuid[:8], None, None


def _mock_competitors(lat, lon, n, dist_nearest, seed):
    rng = random.Random(seed)
    compass = [k * math.pi / 4 for k in range(8)]
    pts = []
    for i in range(max(n, 1)):
        dist = int(dist_nearest) if i == 0 else rng.randint(int(dist_nearest or 80), 480)
        angle = rng.choice(compass) + rng.gauss(0, 0.18)
        pts.append(
            (
                lat + (dist * math.cos(angle)) / 111_320,
                lon + (dist * math.sin(angle)) / (111_320 * math.cos(math.radians(lat))),
                dist,
            )
        )
    return pts


def _semaforo_color(val, umbral_bien, umbral_mal, invert=False):
    if val is None:
        return _C_MUTED
    if not invert:
        return _C_GREEN if val >= umbral_bien else (_C_RED if val <= umbral_mal else _C_AMBER)
    return _C_GREEN if val <= umbral_bien else (_C_RED if val >= umbral_mal else _C_AMBER)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-insights — texto contextual por sección
# ─────────────────────────────────────────────────────────────────────────────


def _auto_insight_captacion(vals):
    pob5 = vals.get("poblacion_5min")
    pob10 = vals.get("poblacion_10min")
    pob15 = vals.get("poblacion_15min")
    if pob5 is None:
        return None
    if pob15 and pob15 > 0:
        pct = pob5 / pob15 * 100
        if pct < 15:
            coment = (
                f"Solo el {pct:.0f}% de esa masa reside en la isócrona 0-5 min; "
                "el establecimiento depende del tráfico de paso del área ampliada."
            )
        else:
            coment = (
                f"El {pct:.0f}% de la población accesible en la isócrona 0-15 min "
                "reside en la isócrona 0-5 min: concentración favorable para compra por impulso."
            )
    else:
        coment = ""
    bloque = f"{pob5:,.0f} personas viven dentro de la isócrona 0-5 min."
    if pob10 and pob15:
        bloque += f" En la isócrona 0-10 min el área crece hasta {pob10:,.0f} y en la isócrona 0-15 min alcanza {pob15:,.0f}."
    return f"{bloque} {coment}".strip()


def _auto_insight_edad(vals):
    p15 = vals.get("pob_15_19") or 0
    p20 = vals.get("pob_20_24") or 0
    p25 = vals.get("pob_25_29") or 0
    p30 = vals.get("pob_30_34") or 0
    p35 = vals.get("pob_35_39") or 0
    peak = p25 + p30
    total_15_39 = p15 + p20 + p25 + p30 + p35
    pob10 = vals.get("poblacion_10min")
    if not total_15_39:
        return None
    pct_target = total_15_39 / pob10 * 100 if pob10 else None
    pct_peak = peak / total_15_39 * 100 if total_15_39 else 0
    txt = f"En 800 m hay {total_15_39:,.0f} personas entre 15 y 39 años"
    if pct_target:
        txt += f", el {pct_target:.0f}% del total de {pob10:,.0f} hab. en esa área"
    txt += f". La cohorte 25–34 concentra el {pct_peak:.0f}% de ese grupo."
    return txt


def _auto_insight_hogar(vals):
    nhog = vals.get("n_hogares_total")
    tam = vals.get("tamanio_medio_hogar")
    jovenes = vals.get("hogares_jovenes_solos") or 0
    parejas_j = vals.get("hogares_parejas_jovenes") or 0
    familias = vals.get("hogares_familias_hijos") or 0
    mono = vals.get("hogares_monoparentales") or 0
    if not nhog:
        return None
    n_target = jovenes + parejas_j + familias
    pct = n_target / nhog * 100 if nhog else 0
    txt = f"Hay {nhog:,.0f} hogares en radio de 800 m"
    if tam:
        txt += f" (media {tam:.1f} personas/hogar)"
    txt += f". De ellos, {n_target:,.0f} ({pct:.0f}%) son jóvenes solos, parejas jóvenes o familias con hijos."
    if mono:
        pct_m = mono / nhog * 100
        txt += f" Las familias monoparentales ({mono:,.0f} hogares, {pct_m:.0f}%) también buscan valor por precio."
    return txt


def _auto_insight_renta(vals):
    renta = vals.get("renta_hogar_anual")
    renta_m = vals.get("renta_hogar_mensual")
    nhog = vals.get("n_hogares_total")
    renta_alta = vals.get("hogares_renta_alta")
    renta_ma = vals.get("hogares_renta_media_alta")
    if renta is None:
        return None
    pct = (renta - _REF_RENTA) / _REF_RENTA * 100
    calif = "por encima" if pct >= 0 else "por debajo"
    txt = f"La renta media del hogar es {renta:,.0f} €/año"
    if renta_m:
        txt += f" ({renta_m:,.0f} €/mes)"
    txt += f", un {abs(pct):.0f}% {calif} de la media nacional."
    if nhog and nhog > 0 and renta_alta is not None:
        pct_alta = (renta_alta + (renta_ma or 0)) / nhog * 100
        txt += (
            f" El {pct_alta:.0f}% de los hogares supera los 2.122 €/mes, "
            f"hay poder adquisitivo real para compra discrecional habitual."
        )
    return txt


def _auto_insight_salud(vals):
    nhog = vals.get("n_hogares_total")
    imprev = vals.get("puede_afrontar_imprevistos_pct")
    pobreza = vals.get("en_riesgo_pobreza_pct")
    if not nhog or imprev is None:
        return None
    pct_i = imprev / nhog * 100
    n_de_10 = round(pct_i / 10)
    txt = f"{n_de_10} de cada 10 hogares pueden asumir un gasto inesperado sin entrar en apuros."
    if pobreza:
        pct_p = pobreza / nhog * 100
        txt += f" Solo el {pct_p:.0f}% está en riesgo de pobreza."
    if pct_i > 65:
        txt += " La zona tiene estabilidad económica suficiente para sostener gasto en moda y ocio de forma habitual."
    else:
        txt += " La base económica es moderada; el precio y la propuesta de valor son factores decisivos para la conversión."
    return txt


def _auto_insight_gasto(vals):
    gasto_ropa = vals.get("gasto_ropa_calzado")
    gasto_pers = vals.get("gasto_cuidado_personal")
    gasto_ocio = vals.get("gasto_ocio_cultura")
    if gasto_ropa is None:
        return None
    pct = (gasto_ropa - _REF_GASTO_ROPA) / _REF_GASTO_ROPA * 100
    verb = "más" if pct >= 0 else "menos"
    txt = (
        f"Los hogares del área gastan {gasto_ropa:,.0f} € al año en ropa y calzado, "
        f"un {abs(pct):.0f}% {verb} que la media nacional ({_REF_GASTO_ROPA:,.0f} €)."
    )
    if gasto_pers:
        txt += (
            f" El gasto en cuidado personal suma {gasto_pers:,.0f} €/hogar, "
            "señal de predisposición a marcas de lifestyle y autocuidado."
        )
    if gasto_ocio:
        txt += f" El ocio y la cultura absorben {gasto_ocio:,.0f} €/hogar, indicando disponibilidad para gasto no esencial."
    return txt


def _auto_insight_online(vals):
    nhog = vals.get("n_hogares_total")
    puthint = vals.get("pct_compras_online")
    propuspo = vals.get("online_ropa_deporte_pct")
    whelain = vals.get("online_ultimo_mes_pct")
    if not nhog or puthint is None:
        return None
    pct_online = puthint / nhog * 100
    txt = f"El {pct_online:.0f}% de los hogares compra habitualmente por internet."
    if propuspo:
        pct_ropa = propuspo / nhog * 100
        txt += (
            f" De ellos, el {pct_ropa:.0f}% ya ha comprado ropa o deporte online, "
            "presión omnicanal directa sobre la categoría."
        )
    if whelain:
        pct_mes = whelain / nhog * 100
        txt += (
            f" El {pct_mes:.0f}% realizó alguna compra online el último mes: "
            "son compradores activos con hábito consolidado, no ocasionales."
        )
    if pct_online > 60:
        txt += " La tienda física compite con Amazon y Zara.com por los mismos bolsillos."
    return txt


# ─────────────────────────────────────────────────────────────────────────────
# Layout helpers
# ─────────────────────────────────────────────────────────────────────────────


def _section_header(icon_cls, title, subtitle=None):
    return html.Div(
        [
            html.Div(
                [
                    html.I(
                        className=f"{icon_cls} me-2",
                        style={"color": _C_PRIMARY, "fontSize": "1.15rem"},
                    ),
                    html.Span(
                        title, style={"fontWeight": "700", "fontSize": "1.18rem", "color": _C_DARK}
                    ),
                ],
                className="d-flex align-items-center",
            ),
            (
                html.P(
                    subtitle,
                    style={
                        "fontSize": "0.82rem",
                        "color": _C_MUTED,
                        "marginBottom": "0",
                        "marginLeft": "1.9rem",
                    },
                )
                if subtitle
                else html.Span()
            ),
        ],
        style={
            "marginBottom": "16px",
            "paddingBottom": "10px",
            "borderBottom": f"2px solid {_C_GRID}",
        },
    )


def _insight_box(text):
    if not text:
        return html.Span()
    return html.Div(
        html.P(
            [
                html.I(
                    className="fas fa-lightbulb me-2",
                    style={"color": _C_AMBER, "fontSize": "0.85rem"},
                ),
                text,
            ],
            className="mb-0",
            style={"fontSize": "0.88rem", "color": _C_DARK, "lineHeight": "1.65"},
        ),
        style={
            "background": "#fffbf0",
            "border": "1px solid #ffe5a0",
            "borderLeft": f"4px solid {_C_AMBER}",
            "borderRadius": "8px",
            "padding": "10px 14px",
            "marginTop": "12px",
        },
    )


def _chart_card(fig, gid, height, title=None, insight=None):
    children = []
    if title:
        children.append(
            html.P(
                title,
                style={
                    "fontSize": "0.65rem",
                    "color": _C_MUTED,
                    "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                    "fontWeight": "600",
                    "marginBottom": "6px",
                },
            )
        )
    children.append(dcc.Graph(id=gid, figure=fig, config=_CFG, style={"height": height}))
    if insight:
        children.append(_insight_box(insight))
    return dbc.Card(
        dbc.CardBody(children, className="p-3"),
        className="border-0 shadow-sm rounded-4 h-100",
        style={"overflow": "visible"},
    )


def _semaforo(val, umbral_bien, umbral_mal, invert=False):
    col = _semaforo_color(val, umbral_bien, umbral_mal, invert)
    name = (
        "Bueno"
        if col == _C_GREEN
        else ("Moderado" if col == _C_AMBER else ("Sin dato" if col == _C_MUTED else "Alerta"))
    )
    bmap = {_C_GREEN: "success", _C_AMBER: "warning", _C_RED: "danger", _C_MUTED: "secondary"}
    return name, bmap.get(col, "secondary")


# ─────────────────────────────────────────────────────────────────────────────
# Metric cards
# ─────────────────────────────────────────────────────────────────────────────


def _build_metric_cards(vals):
    cards = []
    nhog = vals.get("n_hogares_total")

    # ── Captación peatonal ────────────────────────────────────────────────────
    pob5 = vals.get("poblacion_5min")
    pob10 = vals.get("poblacion_10min")
    pob15 = vals.get("poblacion_15min")
    if pob5 is not None:
        nivel = (
            "Potencial alto"
            if pob5 > 5_000
            else ("Potencial medio" if pob5 > 2_000 else "Potencial bajo")
        )
        badge_col = "success" if pob5 > 5_000 else ("warning" if pob5 > 2_000 else "danger")
        funnel = [(f"{pob5:,.0f}", "0-5 min")]
        if pob10:
            funnel.append((f"{pob10:,.0f}", "0-10 min"))
        if pob15:
            funnel.append((f"{pob15:,.0f}", "0-15 min"))
        cards.append(
            dict(
                icon="fas fa-walking",
                label="Captación peatonal",
                main_val=f"{pob5:,.0f}",
                unit="hab. isócrona 0-5 min",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_PRIMARY,
                funnel=funnel,
                detail=None,
            )
        )

    # ── Renta del hogar ───────────────────────────────────────────────────────
    renta_hogar = vals.get("renta_hogar_anual")
    renta_pc = vals.get("renta_per_capita")
    renta_alta = vals.get("hogares_renta_alta")
    renta_ma = vals.get("hogares_renta_media_alta")
    if renta_hogar is not None:
        pct = (renta_hogar - _REF_RENTA) / _REF_RENTA * 100
        nivel = "Sobre media" if pct > 10 else ("En la media" if pct > -10 else "Bajo la media")
        badge_col = "success" if pct > 10 else ("warning" if pct > -10 else "danger")
        signo = f"+{pct:.0f}%" if pct >= 0 else f"{pct:.0f}%"
        detail_parts = [f"{signo} vs media nacional (€{_REF_RENTA:,.0f})"]
        if renta_pc:
            detail_parts.append(f"{renta_pc:,.0f} €/cápita")
        if nhog and renta_alta is not None:
            pct_alta = (renta_alta + (renta_ma or 0)) / nhog * 100
            detail_parts.append(f"{pct_alta:.0f}% hog. renta media-alta+")
        cards.append(
            dict(
                icon="fas fa-euro-sign",
                label="Renta del hogar",
                main_val=f"{renta_hogar:,.0f} €",
                unit="renta anual media (800 m)",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_PURPLE,
                funnel=None,
                detail=" · ".join(detail_parts),
            )
        )

    # ── Gasto ropa y calzado ──────────────────────────────────────────────────
    gasto_ropa = vals.get("gasto_ropa_calzado")
    gasto_pers = vals.get("gasto_cuidado_personal")
    if gasto_ropa is not None:
        pct = (gasto_ropa - _REF_GASTO_ROPA) / _REF_GASTO_ROPA * 100
        nivel = "Gasto alto" if pct > 15 else ("Gasto medio" if pct > -15 else "Gasto bajo")
        badge_col = "success" if pct > 15 else ("warning" if pct > -15 else "danger")
        signo = f"+{pct:.0f}%" if pct >= 0 else f"{pct:.0f}%"
        detail_parts = [f"{signo} vs ref. nacional (€{_REF_GASTO_ROPA:,.0f})"]
        if gasto_pers:
            detail_parts.append(f"cuidado personal {gasto_pers:,.0f} €/hog.")
        cards.append(
            dict(
                icon="fas fa-shopping-bag",
                label="Gasto ropa y calzado",
                main_val=f"{gasto_ropa:,.0f} €",
                unit="por hogar/año en 800 m",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_GREEN,
                funnel=None,
                detail=" · ".join(detail_parts),
            )
        )

    # ── Perfil demográfico target ─────────────────────────────────────────────
    jovenes = vals.get("hogares_jovenes_solos")
    familias = vals.get("hogares_familias_hijos")
    parejas_j = vals.get("hogares_parejas_jovenes")
    if any(v is not None for v in [jovenes, familias, parejas_j]):
        total_target = (jovenes or 0) + (familias or 0) + (parejas_j or 0)
        nivel = (
            "Target alto"
            if total_target > 1_500
            else ("Target medio" if total_target > 600 else "Target bajo")
        )
        badge_col = (
            "success" if total_target > 1_500 else ("warning" if total_target > 600 else "danger")
        )
        parts = []
        if jovenes:
            parts.append(f"{jovenes:,.0f} jóv. solos")
        if parejas_j:
            parts.append(f"{parejas_j:,.0f} parejas jóvenes")
        if familias:
            parts.append(f"{familias:,.0f} familias c/ hijos")
        pct_str = f"{total_target/nhog*100:.0f}% del área" if nhog else None
        cards.append(
            dict(
                icon="fas fa-users",
                label="Hogares target",
                main_val=f"{total_target:,.0f}",
                unit=f"hogares target en 800 m{(' · ' + pct_str) if pct_str else ''}",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_AMBER,
                funnel=None,
                detail=" · ".join(parts) if parts else None,
            )
        )

    # ── Salud financiera ──────────────────────────────────────────────────────
    imprev = vals.get("puede_afrontar_imprevistos_pct")
    facilidad = vals.get("llega_mes_con_facilidad_pct")
    pobreza = vals.get("en_riesgo_pobreza_pct")
    if nhog and imprev is not None:
        pct_i = imprev / nhog * 100
        pct_p = pobreza / nhog * 100 if pobreza and nhog else None
        nivel = (
            "Zona solvente" if pct_i > 70 else ("Zona estable" if pct_i > 50 else "Zona vulnerable")
        )
        badge_col = "success" if pct_i > 70 else ("warning" if pct_i > 50 else "danger")
        detail_parts = [f"{pct_i:.0f}% puede afrontar imprevistos"]
        if pct_p is not None:
            detail_parts.append(f"{pct_p:.0f}% en riesgo de pobreza")
        if facilidad and nhog:
            pct_f = facilidad / nhog * 100
            detail_parts.append(f"{pct_f:.0f}% llega a fin de mes con facilidad")
        cards.append(
            dict(
                icon="fas fa-shield-alt",
                label="Salud financiera del hogar",
                main_val=f"{pct_i:.0f}%",
                unit="hogares con capacidad de afrontar imprevistos",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_TEAL,
                funnel=None,
                detail=" · ".join(detail_parts),
            )
        )

    # ── Canal digital ─────────────────────────────────────────────────────────
    puthint = vals.get("pct_compras_online")
    propuspo = vals.get("online_ropa_deporte_pct")
    if nhog and puthint is not None:
        pct_online = puthint / nhog * 100
        pct_ropa = propuspo / nhog * 100 if propuspo and nhog else None
        nivel = (
            "Presión alta"
            if pct_online > 70
            else ("Presión media" if pct_online > 45 else "Presión baja")
        )
        badge_col = "danger" if pct_online > 70 else ("warning" if pct_online > 45 else "success")
        detail_parts = [f"{pct_online:.0f}% compra online"]
        if pct_ropa:
            detail_parts.append(f"{pct_ropa:.0f}% compra ropa/deporte online")
        cards.append(
            dict(
                icon="fas fa-mobile-alt",
                label="Canal online (presión omnicanal)",
                main_val=f"{pct_online:.0f}%",
                unit="hogares que compran online en 800 m",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_RED,
                funnel=None,
                detail=" · ".join(detail_parts),
            )
        )

    # ── Transporte público (Phase 2) ──────────────────────────────────────────
    dist_t = vals.get("dist_transporte_min_m")
    if dist_t is not None:
        if dist_t < 150:
            nivel, badge_col = "Excelente", "success"
            detail = "Capta el tráfico de la parada directamente"
        elif dist_t < 400:
            nivel, badge_col = "Adecuado", "warning"
            detail = "Visitas de conveniencia desde zonas no peatonales"
        else:
            nivel, badge_col = "Limitado", "danger"
            detail = "Mayor dependencia del vehículo privado"
        cards.append(
            dict(
                icon="fas fa-bus",
                label="Transporte público",
                main_val=f"{dist_t:,.0f} m",
                unit="al nodo más cercano",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_TEAL,
                funnel=None,
                detail=detail,
            )
        )

    # ── Competencia directa (Phase 2) ─────────────────────────────────────────
    n_comp = vals.get("n_competidores_500m")
    dist_c = vals.get("dist_competidor_cercano_m")
    if n_comp is not None:
        if n_comp == 0:
            nivel, badge_col = "Sin competencia", "success"
            main_val, unit, detail = "0", "competidores en 500 m", "Posición de monopolio local"
        else:
            nivel = "Alta presión" if n_comp >= 5 else ("Moderada" if n_comp >= 2 else "Baja")
            badge_col = "danger" if n_comp >= 5 else ("warning" if n_comp >= 2 else "success")
            main_val = str(int(n_comp))
            unit = f"competidor{'es' if n_comp != 1 else ''} en 500 m"
            detail = f"El más cercano a {dist_c:,.0f} m" if dist_c else None
        cards.append(
            dict(
                icon="fas fa-store-alt",
                label="Competencia directa",
                main_val=main_val,
                unit=unit,
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_RED,
                funnel=None,
                detail=detail,
            )
        )

    # ── Movilidad peatonal (Phase 2) ──────────────────────────────────────────
    mob = vals.get("indice_movilidad_peatonal")
    dens = vals.get("densidad_comercial_score")
    if mob is not None:
        nivel = "Alta" if mob >= 0.7 else ("Media" if mob >= 0.4 else "Baja")
        badge_col = "success" if mob >= 0.7 else ("warning" if mob >= 0.4 else "danger")
        detail = None
        if dens is not None:
            dens_lbl = "alta" if dens > 0.7 else ("media" if dens > 0.35 else "baja")
            detail = f"Densidad comercial {dens_lbl} · {dens:.2f}/1.00"
        cards.append(
            dict(
                icon="fas fa-shoe-prints",
                label="Movilidad peatonal",
                main_val=f"{mob:.2f}",
                unit="índice 0–1",
                badge_txt=nivel,
                badge_col=badge_col,
                border_color=_C_GREEN,
                funnel=None,
                detail=detail,
            )
        )

    return cards


def _render_cards(cards_data, max_per_row=3):
    if not cards_data:
        return html.Div()
    cols = []
    for c in cards_data:
        if c["funnel"] and len(c["funnel"]) > 1:
            nodes = []
            for i, (v, lbl) in enumerate(c["funnel"]):
                nodes.append(
                    html.Div(
                        [
                            html.Div(
                                v,
                                style={
                                    "fontWeight": "700",
                                    "fontSize": "0.88rem",
                                    "color": _C_DARK,
                                },
                            ),
                            html.Div(
                                lbl,
                                style={
                                    "fontSize": "0.62rem",
                                    "color": _C_MUTED,
                                    "textAlign": "center",
                                },
                            ),
                        ],
                        style={"textAlign": "center"},
                    )
                )
                if i < len(c["funnel"]) - 1:
                    nodes.append(
                        html.Span(
                            "→",
                            style={
                                "color": _C_MUTED,
                                "fontSize": "0.75rem",
                                "alignSelf": "center",
                                "margin": "0 4px",
                            },
                        )
                    )
            value_block = html.Div(
                className="d-flex align-items-center flex-wrap mt-2 mb-1", children=nodes
            )
        else:
            value_block = html.Div(
                [
                    html.Div(
                        c["main_val"],
                        style={
                            "fontSize": "1.28rem",
                            "fontWeight": "700",
                            "color": _C_DARK,
                            "lineHeight": "1.2",
                            "marginTop": "6px",
                        },
                    ),
                    html.Div(
                        c["unit"],
                        style={"fontSize": "0.67rem", "color": _C_MUTED, "marginBottom": "2px"},
                    ),
                ]
            )

        detail_el = (
            html.Div(
                c["detail"],
                style={
                    "fontSize": "0.70rem",
                    "color": _C_MUTED,
                    "marginTop": "4px",
                    "borderTop": "1px solid #f0f0f0",
                    "paddingTop": "4px",
                },
            )
            if c["detail"]
            else html.Span()
        )

        card = dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        className="d-flex justify-content-between align-items-center",
                        children=[
                            html.Div(
                                [
                                    html.I(
                                        className=f"{c['icon']} me-1",
                                        style={"color": c["border_color"], "fontSize": "0.72rem"},
                                    ),
                                    html.Span(
                                        c["label"],
                                        style={
                                            "fontSize": "0.65rem",
                                            "color": _C_MUTED,
                                            "textTransform": "uppercase",
                                            "letterSpacing": "0.4px",
                                            "fontWeight": "600",
                                        },
                                    ),
                                ]
                            ),
                            dbc.Badge(
                                c["badge_txt"],
                                color=c["badge_col"],
                                pill=True,
                                style={"fontSize": "0.76rem"},
                            ),
                        ],
                    ),
                    value_block,
                    detail_el,
                ],
                className="p-3",
            ),
            className="border-0 shadow-sm rounded-4 h-100",
            style={"borderLeft": f"4px solid {c['border_color']}"},
        )
        lg = 12 // max_per_row
        cols.append(dbc.Col(card, xs=12, sm=6, lg=lg, className="mb-3"))
    return dbc.Row(cols, className="g-3 mb-3")


# ─────────────────────────────────────────────────────────────────────────────
# Charts — Sección A: Alcance
# ─────────────────────────────────────────────────────────────────────────────


def _fig_captacion(vals):
    pob5, pob10, pob15 = (
        vals.get("poblacion_5min"),
        vals.get("poblacion_10min"),
        vals.get("poblacion_15min"),
    )
    specs = []
    if pob5 is not None:
        specs.append(("Isócrona 0-5 min", pob5, "rgba(40,167,69,0.75)", pob5))
    if pob10 is not None:
        specs.append(
            ("Isócrona 0-10 min", max(0, pob10 - (pob5 or 0)), "rgba(243,156,18,0.80)", pob10)
        )
    if pob15 is not None:
        specs.append(
            (
                "Isócrona 0-15 min",
                max(0, pob15 - (pob10 or pob5 or 0)),
                "rgba(0,82,204,0.70)",
                pob15,
            )
        )
    if not specs:
        return None
    labels, values, colors, cum_vals = zip(*specs)
    max_v = max(values) if max(values) > 0 else 1
    fig = go.Figure(
        go.Bar(
            y=list(labels),
            x=list(values),
            orientation="h",
            marker=dict(color=list(colors), line=dict(color="white", width=2)),
            text=[f"{v:,.0f} hab." for v in values],
            textposition="outside",
            constraintext="none",
            textfont=dict(size=11, color=_C_DARK, **_FONT),
            customdata=list(cum_vals),
            hovertemplate="%{y}: <b>%{x:,.0f}</b> pers. en este anillo<br>Total hasta aquí: <b>%{customdata:,.0f}</b><extra></extra>",
        )
    )
    fig.update_layout(
        xaxis=dict(
            title=dict(
                text="Habitantes por anillo isócrono", font=dict(size=11, color=_C_MUTED, **_FONT)
            ),
            showgrid=True,
            gridcolor=_C_GRID,
            tickformat=",",
            tickfont=dict(size=10, **_FONT),
            range=[0, max_v * 1.45],
        ),
        yaxis=dict(
            showgrid=False, tickfont=dict(size=12, color=_C_DARK, **_FONT), autorange="reversed"
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=16, b=44, l=88, r=16),
        hovermode="y unified",
        bargap=0.40,
    )
    return fig


def _fig_piramide_edad(vals):
    """Pirámide de población por franjas de edad en radio 800 m."""

    def _sum(*keys):
        total = sum(vals.get(k) or 0 for k in keys)
        return total if total > 0 else None

    _C_BAR = "rgba(0,82,204,0.55)"

    specs = [
        ("10–14 años", _sum("pob_0_4", "pob_5_9", "pob_10_14")),
        ("15–19 años", vals.get("pob_15_19")),
        ("20–24 años", vals.get("pob_20_24")),
        ("25–29 años", vals.get("pob_25_29")),
        ("30–34 años", vals.get("pob_30_34")),
        ("35–39 años", vals.get("pob_35_39")),
        ("40–54 años", _sum("pob_40_44", "pob_45_49", "pob_50_54")),
        ("55–69 años", _sum("pob_55_59", "pob_60_64", "pob_65_69")),
        ("70+ años", _sum("pob_70_74", "pob_75_79", "pob_80_84", "pob_85_plus")),
    ]

    labels, values = [], []
    for label, v in specs:
        if v is not None:
            labels.append(label)
            values.append(v)

    if not labels:
        return None

    max_v = max(values) if max(values) > 0 else 1
    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=_C_BAR, line=dict(color="white", width=1)),
            text=[f"{v:,.0f}" for v in values],
            textposition="outside",
            constraintext="none",
            textfont=dict(size=11, color=_C_DARK, **_FONT),
            hovertemplate="%{y}: <b>%{x:,.0f}</b> personas (800 m)<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis=dict(
            title=dict(text="Personas en radio 800 m", font=dict(size=11, color=_C_MUTED, **_FONT)),
            showgrid=True,
            gridcolor=_C_GRID,
            tickformat=",",
            tickfont=dict(size=10, **_FONT),
            range=[0, max_v * 1.50],
        ),
        yaxis=dict(
            showgrid=False, tickfont=dict(size=11, color=_C_DARK, **_FONT), autorange="reversed"
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=8, b=8, l=100, r=8),
        hovermode="y unified",
        bargap=0.28,
    )
    return fig


def _fig_estructura_hogar(vals):
    """Vertical bars — all household types at 800 m, sorted by value."""
    specs = [
        ("hogares_jovenes_solos", "Solos\n<35", _C_TEAL),
        ("hogares_parejas_jovenes", "Parejas\njóvenes", "rgba(0,82,204,0.65)"),
        ("hogares_parejas_adultas", "Parejas\nadultas", "rgba(0,82,204,0.40)"),
        ("hogares_familias_hijos", "Familias\nc/hijos", _C_PRIMARY),
        ("hogares_monoparentales", "Monoparen-\ntales", "rgba(243,156,18,0.75)"),
        ("hogares_renta_alta", "Renta\nalta", _C_PURPLE),
        ("hogares_renta_media_alta", "Renta\nmedia-alta", "rgba(142,68,173,0.50)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            labels.append(label)
            values.append(v)
            colors.append(color)

    if not labels:
        return None

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(color=colors, opacity=0.88, line=dict(color="white", width=2)),
            text=[f"{v:,.0f}" for v in values],
            textposition="outside",
            textfont=dict(size=11, color=_C_DARK, **_FONT),
            hovertemplate="%{x}: <b>%{y:,.0f}</b> hogares (800 m)<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK, **_FONT)),
        yaxis=dict(
            title=dict(
                text="Nº hogares en radio 800 m", font=dict(size=11, color=_C_MUTED, **_FONT)
            ),
            showgrid=True,
            gridcolor=_C_GRID,
            tickformat=",",
            tickfont=dict(size=10, **_FONT),
            range=[0, max(values) * 1.28],
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=24, b=8, l=16, r=16),
        bargap=0.38,
    )
    return fig


def _flow_vectors(lat0, lon0, pois, n_rows=9, n_cols=11, arrow_len_m=75):
    """
    Returns (lats, lons) encoding a vector field: one short line segment per grid
    point, oriented toward the weighted centroid of nearby attractions (store + POIs).
    Each vector = [start, end, None] so a single Scattermapbox trace draws all arrows.
    """
    lat_m = 1 / 111_320
    lon_m = 1 / (111_320 * math.cos(math.radians(lat0)))
    half = 1100  # metres — covers isócrona 0-15 min
    half_lat = half * lat_m
    half_lon = half * lon_m

    # Attractions: store (weight 2) + POIs
    atts = [(lat0, lon0, 2.0)]
    for p in pois:
        atts.append((p["lat"], p["lon"], float(p.get("valor", 0.5))))

    all_lats, all_lons = [], []
    for i in range(n_rows):
        for j in range(n_cols):
            glat = lat0 - half_lat + 2 * half_lat * (i + 0.5) / n_rows
            glon = lon0 - half_lon + 2 * half_lon * (j + 0.5) / n_cols
            vx = vy = 0.0
            for alat, alon, w in atts:
                dlat = alat - glat
                dlon = alon - glon
                dist_m = math.sqrt((dlat / lat_m) ** 2 + (dlon / lon_m) ** 2) + 1e-3
                factor = w / dist_m
                vx += dlat * factor
                vy += dlon * factor
            mag = math.sqrt(vx**2 + vy**2) + 1e-12
            elat = glat + (vx / mag) * arrow_len_m * lat_m
            elon = glon + (vy / mag) * arrow_len_m * lon_m
            all_lats += [glat, elat, None]
            all_lons += [glon, elon, None]
    return all_lats, all_lons


def _get_pois(uuid: str) -> list[dict]:
    """Lee POIs desde DB y los adapta al formato de _fig_mapa (label/valor)."""
    try:
        from src.db.queries import get_pois_for_location

        rows = get_pois_for_location(uuid)
        if rows:
            return [
                {
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "label": r["nombre"],
                    "categoria": r["categoria"],
                    "valor": r["valor_relativo"] if r["valor_relativo"] is not None else 0.5,
                    "detalle": r["detalle"] or "",
                    "sonar": r["categoria"] == "tourist_poi",
                }
                for r in rows
            ]
    except Exception:
        pass
    return []


def _fig_mapa(vals, lat, lon, uuid):
    if lat is None or lon is None:
        return None
    n_comp = int(vals.get("n_competidores_500m") or 0)
    dist_near = vals.get("dist_competidor_cercano_m") or 200
    pob5 = vals.get("poblacion_5min")
    comp_seed = int(uuid.replace("-", ""), 16) % (2**31)

    catchment = get_catchment_rings(uuid)
    usa_geo_real = catchment is not None and len(catchment) == 3

    fig = go.Figure()

    # ── Isócronas ────────────────────────────────────────────────────────────────
    ring_specs = [
        (2, "rgba(0,82,204,0.07)", "rgba(0,82,204,0.28)", "Isócrona 0-15 min"),
        (1, "rgba(243,156,18,0.10)", "rgba(243,156,18,0.42)", "Isócrona 0-10 min"),
        (0, "rgba(40,167,69,0.15)", "rgba(40,167,69,0.65)", "Isócrona 0-5 min"),
    ]
    if usa_geo_real:
        for idx, fill_col, line_col, name in ring_specs:
            ring = catchment[idx]
            if ring is None:
                continue
            lats = list(ring["lats"])
            lons = list(ring["lons"])
            for hole in ring.get("holes", []):
                lats += [None] + list(hole["lats"])
                lons += [None] + list(hole["lons"])
            fig.add_trace(
                go.Scattermap(
                    lat=lats,
                    lon=lons,
                    mode="lines",
                    fill="toself",
                    fillcolor=fill_col,
                    line=dict(color=line_col, width=2),
                    name=name,
                    hoverinfo="skip",
                )
            )

    # ── Competidores (pines rojos con clustering) ─────────────────────────────
    if n_comp > 0:
        comps = _mock_competitors(lat, lon, n_comp, dist_near, comp_seed)
        fig.add_trace(
            go.Scattermap(
                lat=[c[0] for c in comps],
                lon=[c[1] for c in comps],
                mode="markers",
                marker=dict(size=14, color=_C_RED, opacity=0.90),
                cluster=dict(
                    enabled=True,
                    color=_C_RED,
                    opacity=0.80,
                    size=22,
                    step=[-1, 5, 15],
                    maxzoom=16,
                ),
                name=f"Competidores ({n_comp})",
                customdata=[c[2] for c in comps],
                hovertemplate="<b>Competidor</b><br>a ~%{customdata:,.0f} m<extra></extra>",
            )
        )

    # ── POIs por categoría (pines de color + clustering) ──────────────────────
    spatial_pois = _get_pois(uuid)
    poi_cat_meta = _load_poi_cat_meta()
    if spatial_pois:
        from itertools import groupby
        from operator import itemgetter

        # Sonar: anillos concéntricos para polos de alta afluencia (sin cluster)
        sonar_items = [p for p in spatial_pois if p.get("sonar")]
        for p in sonar_items:
            color_s = poi_cat_meta.get(p["categoria"], {}).get("color", "#f39c12")
            for ring_size, ring_alpha in [(44, 0.04), (32, 0.09), (20, 0.18)]:
                fig.add_trace(
                    go.Scattermap(
                        lat=[p["lat"]],
                        lon=[p["lon"]],
                        mode="markers",
                        marker=dict(size=ring_size, color=color_s, opacity=ring_alpha),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

        # Pines agrupados por categoría con clustering por zoom
        for cat, items in groupby(
            sorted(spatial_pois, key=itemgetter("categoria")), key=itemgetter("categoria")
        ):
            items = list(items)
            _cat_meta = poi_cat_meta.get(cat, {})
            color = _cat_meta.get("color", "#95a5a6")
            lats = [p["lat"] for p in items]
            lons = [p["lon"] for p in items]
            tips = [f"<b>{p['label']}</b><br>{p.get('detalle', '')}<extra></extra>" for p in items]
            fig.add_trace(
                go.Scattermap(
                    lat=lats,
                    lon=lons,
                    mode="markers",
                    marker=dict(size=14, color=color, opacity=0.92),
                    cluster=dict(
                        enabled=True,
                        color=color,
                        opacity=0.85,
                        size=24,
                        step=[-1, 3, 8],
                        maxzoom=16,
                    ),
                    name=_cat_meta.get("label", cat),
                    hovertemplate=tips,
                )
            )

    # ── Marcador de la tienda (pin azul grande, sin cluster) ──────────────────
    store_tip = "<b>Tu ubicación</b>"
    if pob5:
        store_tip += f"<br>{pob5:,.0f} hab. en isócrona 0-5 min"
    store_tip += "<extra></extra>"
    fig.add_trace(
        go.Scattermap(
            lat=[lat],
            lon=[lon],
            mode="markers",
            marker=dict(size=20, color=_C_PRIMARY),
            name="Ubicación",
            hovertemplate=store_tip,
        )
    )

    # ── Campo vectorial de flujo peatonal (activable desde leyenda) ───────────
    vf_lats, vf_lons = _flow_vectors(lat, lon, spatial_pois if spatial_pois else [])
    fig.add_trace(
        go.Scattermap(
            lat=vf_lats,
            lon=vf_lons,
            mode="lines",
            line=dict(color="#8e44ad", width=1.5),
            opacity=0.70,
            name="Flujo peatonal",
            hoverinfo="skip",
            visible="legendonly",
        )
    )

    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=lat, lon=lon), zoom=14),
        margin=dict(t=0, b=0, l=0, r=0),
        showlegend=True,
        legend=dict(
            orientation="h",
            x=0.01,
            y=0.01,
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor="#ddd",
            borderwidth=1,
            font=dict(size=11, color=_C_DARK, **_FONT),
        ),
        paper_bgcolor="white",
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Charts — Sección B: Capacidad económica
# ─────────────────────────────────────────────────────────────────────────────


def _fig_gasto_comparativo(vals):
    """Horizontal bars — all spending categories, catchment 800 m."""
    specs = [
        ("gasto_comunicaciones", "Comunicaciones", "rgba(23,162,184,0.45)"),
        ("gasto_transporte", "Transporte", "rgba(23,162,184,0.60)"),
        ("gasto_vacaciones", "Vacaciones", "rgba(142,68,173,0.45)"),
        ("gasto_alimentacion", "Alimentación", "rgba(40,167,69,0.65)"),
        ("gasto_restaurantes", "Hoteles y restaurantes", "rgba(23,162,184,0.80)"),
        ("gasto_ocio_cultura", "Ocio y cultura", "rgba(142,68,173,0.70)"),
        ("gasto_cuidado_personal", "Cuidado personal", "rgba(243,156,18,0.75)"),
        ("gasto_calzado", "Calzado", "rgba(0,82,204,0.55)"),
        ("gasto_ropa", "Ropa", "rgba(0,82,204,0.70)"),
        ("gasto_ropa_calzado", "Ropa + calzado ★", "rgba(0,82,204,0.92)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            labels.append(label)
            values.append(v)
            colors.append(color)

    if not labels:
        return None

    max_v = max(values)
    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=colors, line=dict(color="white", width=1)),
            text=[f"{v:,.0f} €/hog." for v in values],
            textposition="outside",
            constraintext="none",
            textfont=dict(size=10, color=_C_DARK, **_FONT),
            hovertemplate="%{y}: <b>%{x:,.0f} €</b>/hogar/año<extra></extra>",
        )
    )

    # Reference line for ropa+calzado benchmark
    fig.add_vline(
        x=_REF_GASTO_ROPA,
        line_dash="dash",
        line_color="rgba(220,53,69,0.5)",
        line_width=1.5,
        annotation_text=f"Ref. nacional ropa+calzado ({_REF_GASTO_ROPA:,.0f} €)",
        annotation_position="top right",
        annotation_font=dict(size=9, color=_C_RED),
    )

    fig.update_layout(
        xaxis=dict(
            title=dict(
                text="€ por hogar / año — radio 800 m", font=dict(size=11, color=_C_MUTED, **_FONT)
            ),
            showgrid=True,
            gridcolor=_C_GRID,
            tickformat=",",
            tickfont=dict(size=10, **_FONT),
            range=[0, max_v * 1.40],
        ),
        yaxis=dict(
            showgrid=False, tickfont=dict(size=10, color=_C_DARK, **_FONT), autorange="reversed"
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=28, b=44, l=152, r=12),
        hovermode="y unified",
        bargap=0.30,
    )
    return fig


def _fig_salud_financiera(vals):
    """Horizontal bars showing financial health as % of households."""
    nhog = vals.get("n_hogares_total")
    if not nhog:
        return None

    specs = [
        ("puede_afrontar_imprevistos_pct", "Puede afrontar\nimprevistos", "rgba(40,167,69,0.80)"),
        (
            "llega_mes_con_facilidad_pct",
            "Llega a fin de\nmes con facilidad",
            "rgba(23,162,184,0.75)",
        ),
        ("en_riesgo_pobreza_pct", "En riesgo\nde pobreza", "rgba(220,53,69,0.70)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            pct = v / nhog * 100
            labels.append(label)
            values.append(round(pct, 1))
            colors.append(color)

    if not labels:
        return None

    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=colors, line=dict(color="white", width=2)),
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
            constraintext="none",
            textfont=dict(size=13, color=_C_DARK, **_FONT),
            hovertemplate="%{y}: <b>%{x:.1f}%</b> de los hogares<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis=dict(
            title=dict(text="% de hogares en 800 m", font=dict(size=11, color=_C_MUTED, **_FONT)),
            showgrid=True,
            gridcolor=_C_GRID,
            ticksuffix="%",
            tickfont=dict(size=10, **_FONT),
            range=[0, max(values) * 1.45],
        ),
        yaxis=dict(
            showgrid=False, tickfont=dict(size=11, color=_C_DARK, **_FONT), autorange="reversed"
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=8, b=44, l=138, r=8),
        hovermode="y unified",
        bargap=0.38,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Charts — Sección C: Comportamiento digital
# ─────────────────────────────────────────────────────────────────────────────


def _fig_canal_online(vals):
    """Horizontal bars — online shopping metrics as % of households."""
    nhog = vals.get("n_hogares_total")
    if not nhog:
        return None

    specs = [
        ("online_ultimo_mes_pct", "Compró online el\núltimo mes", "rgba(220,53,69,0.50)"),
        ("online_ropa_deporte_pct", "Ha comprado ropa/\ndeporte online", "rgba(220,53,69,0.75)"),
        ("pct_compras_online", "Compra online\n(habitual)", "rgba(220,53,69,0.95)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            pct = v / nhog * 100
            labels.append(label)
            values.append(round(pct, 1))
            colors.append(color)

    if not labels:
        return None

    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=colors, line=dict(color="white", width=2)),
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
            constraintext="none",
            textfont=dict(size=13, color=_C_DARK, **_FONT),
            hovertemplate="%{y}: <b>%{x:.1f}%</b> de los hogares<extra></extra>",
        )
    )
    fig.add_vline(
        x=50,
        line_dash="dash",
        line_color="rgba(100,100,100,0.3)",
        line_width=1.5,
        annotation_text="50%",
        annotation_font=dict(size=9, color=_C_MUTED),
        annotation_position="top",
    )
    fig.update_layout(
        xaxis=dict(
            title=dict(text="% de hogares en 800 m", font=dict(size=11, color=_C_MUTED, **_FONT)),
            showgrid=True,
            gridcolor=_C_GRID,
            ticksuffix="%",
            tickfont=dict(size=10, **_FONT),
            range=[0, max(values) * 1.40],
        ),
        yaxis=dict(
            showgrid=False, tickfont=dict(size=11, color=_C_DARK, **_FONT), autorange="reversed"
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=20, b=44, l=155, r=8),
        hovermode="y unified",
        bargap=0.38,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Ensamblaje público
# ─────────────────────────────────────────────────────────────────────────────


def generar_panel_geo_visual(location_uuid, vals, clima=None, fecha_captura=None):
    activos = {k: v for k, v in vals.items() if v is not None}
    nombre, lat, lon = _info_ubicacion(location_uuid)
    all_cards = _build_metric_cards(activos)

    if not activos:
        return html.Div(
            dbc.Card(
                dbc.CardBody(
                    html.P(
                        "Variables geoespaciales pendientes de integración.",
                        className="text-muted small mb-0",
                    )
                ),
                className="border-0 shadow-sm rounded-4 mb-3 bg-white",
            )
        )

    # ── Tarjetas A: Alcance ───────────────────────────────────────────────────
    cards_a = [c for c in all_cards if c["label"] in {"Captación peatonal", "Hogares target"}]
    # ── Tarjetas B: Capacidad económica ───────────────────────────────────────
    cards_b = [
        c
        for c in all_cards
        if c["label"] in {"Renta del hogar", "Salud financiera del hogar", "Mercado inmobiliario"}
    ]
    # ── Tarjetas C: Gasto y digital ───────────────────────────────────────────
    cards_c = [
        c
        for c in all_cards
        if c["label"] in {"Gasto ropa y calzado", "Canal online (presión omnicanal)"}
    ]
    # ── Tarjetas D: Entorno competitivo (Phase 2) ─────────────────────────────
    cards_d = [
        c
        for c in all_cards
        if c["label"] in {"Transporte público", "Competencia directa", "Movilidad peatonal"}
    ]

    # ── Charts ───────────────────────────────────────────────────────────────
    fig_cap = _fig_captacion(activos)
    fig_mapa = _fig_mapa(activos, lat, lon, location_uuid)
    fig_edad = _fig_piramide_edad(activos)
    fig_hogar = _fig_estructura_hogar(activos)
    fig_gasto = _fig_gasto_comparativo(activos)
    fig_salud = _fig_salud_financiera(activos)
    fig_online = _fig_canal_online(activos)

    uid = location_uuid[:8]

    def _row(cols):
        return dbc.Row(cols, className="g-3 mb-3")

    # Pre-generar todos los insights (texto enriquecido para PM)
    ins_captacion = _auto_insight_captacion(activos)
    ins_edad = _auto_insight_edad(activos)
    ins_hogar = _auto_insight_hogar(activos)
    ins_renta = _auto_insight_renta(activos)
    ins_salud = _auto_insight_salud(activos)
    ins_gasto = _auto_insight_gasto(activos)
    ins_online = _auto_insight_online(activos)

    # ── SECCIÓN A: ALCANCE PEATONAL ───────────────────────────────────────────
    # El mapa lleva el insight de captación; las barras llevan el de edad+hogar
    sec_a_charts = []
    if fig_cap:
        sec_a_charts.append(
            dbc.Col(
                _chart_card(
                    fig_cap,
                    f"geo-cap-{uid}",
                    _H_CHART,
                    title="Población al alcance a pie · isócronas 0-5 / 0-10 / 0-15 min",
                ),
                xs=12,
                lg=5,
                className="mb-3",
            )
        )
    if fig_mapa:
        iso_label = (
            "Área de influencia · isócronas 0-5, 0-10 y 0-15 min"
            if get_catchment_rings(location_uuid)
            else "Área de influencia · isócronas aproximadas"
        )
        sec_a_charts.append(
            dbc.Col(
                _chart_card(
                    fig_mapa, f"geo-map-{uid}", _H_CHART, title=iso_label, insight=ins_captacion
                ),
                xs=12,
                lg=7,
                className="mb-3",
            )
        )

    sec_a_charts2 = []
    if fig_edad:
        sec_a_charts2.append(
            dbc.Col(
                _chart_card(
                    fig_edad,
                    f"geo-edad-{uid}",
                    _H_CHART,
                    title="Pirámide de edad · radio 800 m",
                    insight=ins_edad,
                ),
                xs=12,
                lg=6,
                className="mb-3",
            )
        )
    if fig_hogar:
        sec_a_charts2.append(
            dbc.Col(
                _chart_card(
                    fig_hogar,
                    f"geo-hogar-{uid}",
                    _H_MID,
                    title="Composición del hogar · tipos de familia en 800 m",
                    insight=ins_hogar,
                ),
                xs=12,
                lg=6,
                className="mb-3",
            )
        )

    seccion_a = html.Div(
        [
            _section_header(
                "fas fa-walking",
                "Alcance peatonal",
                "¿Cuántas personas pueden llegar a pie y cuál es su perfil demográfico?",
            ),
            _render_cards(cards_a, max_per_row=4),
            _row(sec_a_charts),
            _row(sec_a_charts2),
        ],
        className="mb-4",
    )

    # ── SECCIÓN B: CAPACIDAD ECONÓMICA ────────────────────────────────────────
    # Gasto lleva insight de gasto+renta; salud lleva insight de salud; inmobiliario el suyo
    sec_b_charts = []
    if fig_gasto:
        sec_b_charts.append(
            dbc.Col(
                _chart_card(
                    fig_gasto,
                    f"geo-gasto-{uid}",
                    "460px",
                    title="Gasto por categoría · €/hogar/año en radio 800 m",
                    insight=ins_gasto,
                ),
                xs=12,
                lg=8,
                className="mb-3",
            )
        )
    salud_inmob_col = []
    if fig_salud:
        salud_inmob_col.append(
            dbc.Col(
                _chart_card(
                    fig_salud,
                    f"geo-salud-{uid}",
                    _H_SM,
                    title="Salud financiera del hogar · radio 800 m",
                    insight=ins_salud,
                ),
                xs=12,
                className="mb-3",
            )
        )
    if salud_inmob_col:
        sec_b_charts.append(
            dbc.Col(
                html.Div(salud_inmob_col),
                xs=12,
                lg=4,
                className="mb-3",
            )
        )

    # La tarjeta de renta lleva su propio insight (sin gráfico propio — se muestra bajo las tarjetas)
    seccion_b = html.Div(
        [
            _section_header(
                "fas fa-euro-sign",
                "Capacidad económica",
                "¿Tienen renta y estabilidad financiera para gastar de forma habitual?",
            ),
            _render_cards(cards_b, max_per_row=3),
            _insight_box(ins_renta),
            _row(sec_b_charts),
        ],
        className="mb-4",
    )

    # ── SECCIÓN C: COMPORTAMIENTO DIGITAL ─────────────────────────────────────
    sec_c_charts = []
    if fig_online:
        sec_c_charts.append(
            dbc.Col(
                _chart_card(
                    fig_online,
                    f"geo-online-{uid}",
                    _H_SM,
                    title="Hábito de compra online · hogares en radio 800 m",
                    insight=ins_online,
                ),
                xs=12,
            )
        )

    seccion_c = html.Div(
        [
            _section_header(
                "fas fa-mobile-alt",
                "Comportamiento digital",
                "¿Compran por internet y cuánta presión ejerce eso sobre la tienda física?",
            ),
            _render_cards(cards_c, max_per_row=4),
            _row(sec_c_charts) if sec_c_charts else html.Div(),
        ],
        className="mb-4",
    )

    # ── SECCIÓN D: ENTORNO COMPETITIVO (Phase 2) ──────────────────────────────
    has_phase2 = any(
        activos.get(k) is not None
        for k in ["dist_transporte_min_m", "n_competidores_500m", "indice_movilidad_peatonal"]
    )
    seccion_d = html.Div()
    if has_phase2 and cards_d:
        seccion_d = html.Div(
            [
                _section_header(
                    "fas fa-map-marker-alt",
                    "Entorno competitivo",
                    "¿Qué tan accesible es la ubicación y a cuánta competencia directa se enfrenta?",
                ),
                _render_cards(cards_d, max_per_row=3),
            ],
            className="mb-4",
        )
    elif not has_phase2:
        seccion_d = dbc.Alert(
            [
                html.I(className="fas fa-info-circle me-2"),
                "Datos de entorno competitivo pendientes — se activan con Places API y Routing (Fase 2).",
            ],
            color="secondary",
            className="small py-2 px-3 rounded-4 mb-4",
        )

    return html.Div(
        [
            seccion_a,
            seccion_b,
            seccion_c,
            seccion_d,
        ]
    )


# ── Mapa Leaflet (pines + clustering) ────────────────────────────────────────


def _leaflet_mapa(vals: dict, lat: float, lon: float, uuid: str):
    """Mapa dash-leaflet con pines SVG por categoría y clustering por zoom."""
    pob5 = vals.get("poblacion_5min")

    layers = [
        dl.TileLayer(
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
            attribution="© OpenStreetMap contributors © CARTO",
            maxZoom=19,
        )
    ]

    # Isócronas — del mayor al menor para que los menores queden encima
    catchment = get_catchment_rings(uuid)
    ring_styles = [
        (2, "#0052CC", 0.07, 0.30),
        (1, "#f39c12", 0.10, 0.45),
        (0, "#28A745", 0.15, 0.65),
    ]
    if catchment and len(catchment) == 3:
        for idx, color_hex, fill_op, stroke_op in ring_styles:
            ring = catchment[idx]
            if ring is None:
                continue
            coords = [list(zip(ring["lons"], ring["lats"]))]
            for hole in ring.get("holes", []):
                coords.append(list(zip(hole["lons"], hole["lats"])))
            layers.append(
                dl.GeoJSON(
                    data={
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": coords},
                    },
                    style={
                        "color": color_hex,
                        "weight": 2,
                        "opacity": stroke_op,
                        "fillColor": color_hex,
                        "fillOpacity": fill_op,
                    },
                    id=f"ring-{idx}-{uuid[:8]}",
                )
            )

    # POIs por categoría con clustering
    spatial_pois = _get_pois(uuid)
    poi_cat_meta = _load_poi_cat_meta()
    if spatial_pois:
        from itertools import groupby
        from operator import itemgetter

        for cat, items in groupby(
            sorted(spatial_pois, key=itemgetter("categoria")), key=itemgetter("categoria")
        ):
            items = list(items)
            color = poi_cat_meta.get(cat, {}).get("color", "#95a5a6")
            layers.append(
                dl.GeoJSON(
                    data={
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                                "properties": {
                                    "name": p["label"],
                                    "detalle": p.get("detalle", ""),
                                    "color": color,
                                },
                            }
                            for p in items
                        ],
                    },
                    cluster=True,
                    pointToLayer=_JS_POINT_TO_LAYER,
                    zoomToBoundsOnClick=True,
                    superClusterOptions={"radius": 80, "maxZoom": 15},
                    id=f"poi-{cat}-{uuid[:8]}",
                )
            )

    # Marcador de la tienda
    store_tip = "Tu ubicación"
    if pob5:
        store_tip += f" · {pob5:,.0f} hab. en 5 min"
    layers.append(
        dl.CircleMarker(
            center=[lat, lon],
            radius=12,
            color="white",
            weight=3,
            fillColor=_C_PRIMARY,
            fillOpacity=1.0,
            children=[dl.Tooltip(store_tip)],
        )
    )

    return dl.MapContainer(
        layers,
        center=[lat, lon],
        zoom=14,
        style={"height": "520px", "width": "100%"},
        id=f"leaflet-map-{uuid[:8]}",
    )


# ── Mapa standalone (visible sin abrir acordeón) ──────────────────────────────


def generar_mapa_contexto(location_uuid: str, vals: dict) -> html.Div | None:
    """
    Devuelve una tarjeta compacta con el mapa de isócronas + POIs para renderizar
    directamente en el panel (sin acordeón).  Retorna None si no hay coordenadas.
    """
    nombre, lat, lon = _info_ubicacion(location_uuid)
    if lat is None or lon is None:
        return None

    activos = {k: v for k, v in vals.items() if v is not None}

    catchment = get_catchment_rings(location_uuid)
    leyenda_rings = []
    if catchment:
        leyenda_rings = [
            html.Span(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "10px",
                            "height": "10px",
                            "borderRadius": "2px",
                            "backgroundColor": c,
                            "marginRight": "4px",
                        }
                    ),
                    html.Span(label, className="text-muted small me-3"),
                ]
            )
            for c, label in [
                ("#28A745", "0–5 min"),
                ("#f39c12", "0–10 min"),
                ("#0052CC", "0–15 min"),
            ]
        ]

    return html.Div(
        [
            html.Div(
                [
                    html.I(className="fas fa-map-marked-alt me-2 text-primary"),
                    html.Span("Contexto espacial", className="fw-bold small text-uppercase"),
                    html.Span(
                        " · " + nombre if nombre else "",
                        className="text-muted small ms-1",
                    ),
                    html.Div(leyenda_rings, className="ms-auto d-flex align-items-center"),
                ],
                className="d-flex align-items-center px-3 py-2 border-bottom bg-white",
            ),
            _leaflet_mapa(activos, lat, lon, location_uuid),
        ],
        className="border-0 shadow-sm rounded-4 overflow-hidden mb-3 bg-white",
    )
