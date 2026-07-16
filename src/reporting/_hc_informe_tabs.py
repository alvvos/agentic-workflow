"""
Informe tabs: Resumen semanal/mensual · Contexto Exterior · Contexto Interior.
"""

from __future__ import annotations

from datetime import date, timedelta

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

# ── City → CCAA subdivision for the holidays library ────────────────────────
_CIUDAD_SUBDIV: dict[str, str] = {
    "Madrid": "MD",
    "Málaga": "AN",
    "Malaga": "AN",
    "Barcelona": "CT",
    "Valencia": "VC",
    "Sevilla": "AN",
    "Seville": "AN",
    "Bilbao": "PV",
    "Zaragoza": "AR",
    "Alicante": "VC",
    "Granada": "AN",
    "Murcia": "MC",
    "Palma": "IB",
    "Palma de Mallorca": "IB",
    "Las Palmas": "CN",
    "Santa Cruz de Tenerife": "CN",
    "San Sebastián": "PV",
    "Donostia": "PV",
    "Córdoba": "AN",
    "Valladolid": "CL",
    "Toledo": "CM",
    "Santander": "CB",
    "Logroño": "RI",
    "Pamplona": "NC",
    "Santiago de Compostela": "GA",
    "Oviedo": "AS",
    "Mérida": "EX",
}

_ZONE_LABEL_FORMAL = {0: "La zona de caja", 1: "La tienda", 2: "La zona exterior"}
_ZONE_ICON = {0: "fas fa-cash-register", 1: "fas fa-store", 2: "fas fa-street-view"}
_ZONE_COLOR = {0: "#6c757d", 1: "#0052CC", 2: "#28A745"}

# (señal_id, display_label, unit_suffix, agg_method)
_SIGNAL_CFG: list[tuple[str, str, str, str]] = [
    ("llueve", "Días con lluvia", " días", "count_positive"),
    ("temp_max", "Temperatura máx. media", "°C", "mean"),
    ("temp_min", "Temperatura mín. media", "°C", "mean"),
    ("escala_crucero", "Escalas de crucero", "", "count_positive"),
    ("n_pasajeros_crucero_dia", "Pasajeros crucero (est.)", "", "sum_int"),
    ("n_pasajeros_crucero_oficial", "Pasajeros crucero (of.)", "", "sum_int"),
]

_DIA_NAMES = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]


# ── Date / location helpers ──────────────────────────────────────────────────


def _to_date(val) -> date:
    if isinstance(val, pd.Timestamp):
        return val.date()
    if hasattr(val, "date") and callable(val.date):
        return val.date()
    return val


def _get_location_meta(location_uuid: str) -> tuple[str, str]:
    try:
        from src.db.store import get_conn

        row = (
            get_conn()
            .execute(
                "SELECT pais_codigo, ciudad FROM ubicaciones WHERE ubicacion_id = ?",
                [location_uuid],
            )
            .fetchone()
        )
        return (row[0] or "ES", row[1] or "") if row else ("ES", "")
    except Exception:
        return "ES", ""


def _get_festivos(pais_codigo: str, ciudad: str, years: set[int]) -> dict[date, str]:
    try:
        import holidays as hol

        subdiv = _CIUDAD_SUBDIV.get(ciudad)
        country = (pais_codigo or "ES").upper()
        result: dict[date, str] = {}
        for year in sorted(years):
            try:
                h = hol.country_holidays(country, subdiv=subdiv, years=year, language="es")
                result.update(dict(h))
            except Exception:
                try:
                    h = hol.country_holidays(country, subdiv=subdiv, years=year)
                    result.update(dict(h))
                except Exception:
                    try:
                        h = hol.country_holidays(country, years=year)
                        result.update(dict(h))
                    except Exception:
                        pass
        return result
    except ImportError:
        return {}


def _dias_apertura(fmin: date, fmax: date, festivos: dict[date, str]) -> int:
    """Mon–Sat days in [fmin, fmax] that are not public holidays."""
    count = 0
    d = fmin
    while d <= fmax:
        if d.weekday() < 6 and d not in festivos:
            count += 1
        d += timedelta(days=1)
    return count


# ── Value formatters ─────────────────────────────────────────────────────────


def _agg_señal(serie: pd.Series, method: str) -> float | int | None:
    if serie is None or serie.empty:
        return None
    if method == "count_positive":
        return int((serie > 0).sum())
    if method == "mean":
        non_zero = serie[serie != 0]
        return round(float(non_zero.mean()), 1) if not non_zero.empty else None
    if method == "sum_int":
        v = int(serie.sum())
        return v if v > 0 else None
    return None


def _fmt_val(val: float | int | None, suffix: str, method: str) -> str:
    if val is None:
        return "—"
    if method == "mean":
        return f"{val:.1f}{suffix}"
    return f"{int(val):,}{suffix}".replace(",", ".")


# ── Sentence generators ──────────────────────────────────────────────────────


def _periodo_labels(ventana: str) -> tuple[str, str, str]:
    """(per_act, lbl_sa, lbl_msa) — lowercase, ready for sentence composition."""
    if ventana == "mes":
        return (
            "en el período analizado",
            "el período anterior",
            "el mismo período del año pasado",
        )
    return "esta semana", "la semana anterior", "la misma semana del año pasado"


def _diff_clause(
    diff: float | int | None,
    ref_str: str | None,
    lbl: str,
    suffix: str = "",
    decimals: int = 0,
) -> str | None:
    """
    Generates the comparison clause:
      '184 más que la semana anterior (1.050)'
      'igual que la semana anterior (1.050)'
      None when there is no reference data.
    """
    if diff is None or ref_str is None:
        return None
    if diff == 0:
        return f"igual que {lbl} ({ref_str})"
    more = "más" if diff > 0 else "menos"
    abs_d = abs(diff)
    d_str = f"{abs_d:.{decimals}f}{suffix}" if decimals > 0 else f"{int(round(abs_d))}{suffix}"
    return f"{d_str} {more} que {lbl} ({ref_str})"


def _compose(inicio: str, *clauses: str | None) -> str:
    """Joins inicio + comparison clauses into a single formal sentence."""
    parts = [c for c in clauses if c is not None]
    if not parts:
        return inicio + "."
    return inicio + ", " + " y ".join(parts) + "."


def _p(text: str) -> html.P:
    return html.P(
        text,
        style={
            "fontSize": "0.83rem",
            "marginBottom": "6px",
            "lineHeight": "1.65",
            "color": "#343a40",
        },
    )


def _sentence_visitantes(
    zone_enum: int,
    vis: int,
    vis_sa: int | None,
    vis_msa: int | None,
    ventana: str,
) -> html.P:
    per, lbl_sa, lbl_msa = _periodo_labels(ventana)
    sujeto = _ZONE_LABEL_FORMAL.get(zone_enum, "La zona")
    vis_str = f"{vis:,}".replace(",", ".")
    inicio = f"{sujeto} registró {vis_str} visitantes {per}"
    ref_sa = f"{vis_sa:,}".replace(",", ".") if vis_sa is not None else None
    ref_msa = f"{vis_msa:,}".replace(",", ".") if vis_msa is not None else None
    diff_sa = vis - vis_sa if vis_sa is not None else None
    diff_msa = vis - vis_msa if vis_msa is not None else None
    return _p(
        _compose(
            inicio, _diff_clause(diff_sa, ref_sa, lbl_sa), _diff_clause(diff_msa, ref_msa, lbl_msa)
        )
    )


def _sentence_dias_apertura(
    ap_act: int,
    dias_v: int,
    ap_sa: int,
    ap_msa: int,
    ventana: str,
) -> html.P:
    per, lbl_sa, lbl_msa = _periodo_labels(ventana)
    per_cap = per[0].upper() + per[1:]
    inicio = f"{per_cap} hubo {ap_act} de {dias_v} días de apertura posibles"
    diff_sa = ap_act - ap_sa
    diff_msa = ap_act - ap_msa
    return _p(
        _compose(
            inicio,
            _diff_clause(diff_sa, str(ap_sa), lbl_sa),
            _diff_clause(diff_msa, str(ap_msa), lbl_msa),
        )
    )


def _inicio_señal(señal_id: str, val_act: float | int, val_str: str, ventana: str) -> str:
    per, _, _ = _periodo_labels(ventana)
    per_cap = per[0].upper() + per[1:]

    if señal_id == "llueve":
        if val_act == 0:
            return f"{per_cap} no llovió"
        if val_act == 1:
            return f"{per_cap} llovió un día"
        return f"{per_cap} llovió {int(val_act)} días"

    if señal_id == "temp_max":
        return f"La temperatura máxima media fue de {val_str} {per}"

    if señal_id == "temp_min":
        return f"La temperatura mínima media fue de {val_str} {per}"

    if señal_id == "escala_crucero":
        if val_act == 0:
            return f"{per_cap} no hubo escalas de crucero"
        if val_act == 1:
            return f"{per_cap} se registró una escala de crucero"
        return f"{per_cap} se registraron {int(val_act)} escalas de crucero"

    if señal_id == "n_pasajeros_crucero_dia":
        return f"El volumen estimado de pasajeros de crucero fue de {val_str} {per}"

    if señal_id == "n_pasajeros_crucero_oficial":
        return f"El volumen oficial de pasajeros de crucero fue de {val_str} {per}"

    return f"{val_str} {per}"


def _sentence_señal(
    señal_id: str,
    val_act: float | int,
    suffix: str,
    method: str,
    val_sa: float | int | None,
    val_msa: float | int | None,
    ventana: str,
) -> html.P:
    _, lbl_sa, lbl_msa = _periodo_labels(ventana)
    val_str = _fmt_val(val_act, suffix, method)
    decimals = 1 if method == "mean" else 0
    diff_suffix = suffix if method == "mean" else ""

    inicio = _inicio_señal(señal_id, val_act, val_str, ventana)
    ref_sa = _fmt_val(val_sa, suffix, method) if val_sa is not None else None
    ref_msa = _fmt_val(val_msa, suffix, method) if val_msa is not None else None
    diff_sa = float(val_act) - float(val_sa) if val_sa is not None else None
    diff_msa = float(val_act) - float(val_msa) if val_msa is not None else None

    return _p(
        _compose(
            inicio,
            _diff_clause(diff_sa, ref_sa, lbl_sa, suffix=diff_suffix, decimals=decimals),
            _diff_clause(diff_msa, ref_msa, lbl_msa, suffix=diff_suffix, decimals=decimals),
        )
    )


# ── Sub-section header ───────────────────────────────────────────────────────


def _sub_header(icon_cls: str, text: str, color: str) -> html.Div:
    return html.Div(
        [
            html.I(className=f"{icon_cls} me-2", style={"color": color, "fontSize": "0.78rem"}),
            html.Span(
                text,
                style={"fontWeight": "600", "fontSize": "0.83rem", "color": "#343a40"},
            ),
        ],
        className="mb-2 mt-3",
    )


# ── Calendar ─────────────────────────────────────────────────────────────────


def _build_calendar(fmin: date, fmax: date, festivos: dict[date, str]) -> html.Div:
    start = fmin - timedelta(days=fmin.weekday())
    end_d = fmax + timedelta(days=(6 - fmax.weekday()))

    header = html.Tr(
        [
            html.Th(
                d,
                style={
                    "fontSize": "0.67rem",
                    "textAlign": "center",
                    "color": "#dc3545" if i >= 5 else "#6c757d",
                    "padding": "2px 4px",
                    "fontWeight": "600",
                },
            )
            for i, d in enumerate(_DIA_NAMES)
        ]
    )

    rows = [header]
    d = start
    while d <= end_d:
        cells = []
        for _ in range(7):
            in_period = fmin <= d <= fmax
            is_festivo = d in festivos
            is_sunday = d.weekday() == 6
            is_saturday = d.weekday() == 5

            if not in_period:
                bg, color, fw, border = "transparent", "#dee2e6", "normal", "none"
            elif is_festivo:
                bg, color, fw, border = "#fff3cd", "#856404", "600", "1px solid #ffc107"
            elif is_sunday:
                bg, color, fw, border = "#f8f9fa", "#adb5bd", "normal", "1px solid #e9ecef"
            elif is_saturday:
                bg, color, fw, border = "#f0f4fb", "#6c757d", "normal", "1px solid #e9ecef"
            else:
                bg, color, fw, border = "#ffffff", "#212529", "normal", "1px solid #e9ecef"

            festivo_name = festivos.get(d, "")
            children: list = [html.Span(str(d.day), style={"display": "block", "fontWeight": fw})]
            if festivo_name and in_period:
                short = festivo_name.split("(")[0].strip()
                if len(short) > 12:
                    short = short[:11] + "…"
                children.append(
                    html.Span(
                        short,
                        style={
                            "fontSize": "0.50rem",
                            "display": "block",
                            "lineHeight": "1.1",
                            "color": "#856404",
                            "wordBreak": "break-word",
                        },
                    )
                )

            cells.append(
                html.Td(
                    children,
                    style={
                        "textAlign": "center",
                        "fontSize": "0.74rem",
                        "padding": "3px 2px",
                        "backgroundColor": bg,
                        "color": color,
                        "borderRadius": "4px",
                        "minWidth": "34px",
                        "verticalAlign": "top",
                        "border": border,
                    },
                )
            )
            d += timedelta(days=1)
        rows.append(html.Tr(cells))

    return html.Div(
        html.Table(
            rows,
            style={
                "width": "100%",
                "borderCollapse": "separate",
                "borderSpacing": "2px",
                "tableLayout": "fixed",
            },
        ),
        style={"overflowX": "auto", "marginTop": "6px"},
    )


# ── Tab content builders ──────────────────────────────────────────────────────


def _tab_resumen(
    zonas_data: list[dict],
    df: pd.DataFrame,
    fmin_p: date,
    fecha_max: date,
    ventana: str,
) -> html.Div:
    fmin_msaa = fmin_p - timedelta(days=364)
    fmax_msaa = fecha_max - timedelta(days=364)

    by_enum: dict[int, dict] = {}
    for z in zonas_data:
        ze = z.get("zone_enum")
        if ze is None:
            continue
        if ze not in by_enum:
            by_enum[ze] = {"zona_names": [], "vis_act": 0, "vis_sama": 0, "vis_msaa": 0}
        by_enum[ze]["zona_names"].append(z["zona"])
        by_enum[ze]["vis_act"] += z["r"].get("visitantes", 0)
        by_enum[ze]["vis_sama"] += z["a"].get("visitantes", 0)

    if not df.empty and "unique_visitors" in df.columns and "Zona" in df.columns:
        for grp in by_enum.values():
            mask = (
                df["Zona"].isin(grp["zona_names"])
                & (df["fecha_dt"] >= fmin_msaa)
                & (df["fecha_dt"] <= fmax_msaa)
            )
            grp["vis_msaa"] = int(df.loc[mask, "unique_visitors"].sum())

    if not by_enum:
        return html.P("Sin datos de zona disponibles.", className="text-muted small")

    sentences = []
    for ze in sorted(by_enum.keys(), reverse=True):  # exterior (2) first
        grp = by_enum[ze]
        vis = grp["vis_act"]
        vis_sa = grp["vis_sama"] if grp["vis_sama"] > 0 else None
        vis_msa = grp["vis_msaa"] if grp["vis_msaa"] > 0 else None
        sentences.append(_sentence_visitantes(ze, vis, vis_sa, vis_msa, ventana))

    lbl_sa = "período anterior" if ventana == "mes" else "semana anterior"
    lbl_msa = "mismo período año anterior" if ventana == "mes" else "misma semana año anterior"
    footer = html.P(
        [
            html.Span("SA = ", style={"fontWeight": "600"}),
            f"{lbl_sa}  ·  ",
            html.Span("MSA = ", style={"fontWeight": "600"}),
            lbl_msa,
        ],
        className="text-muted mb-0 mt-2",
        style={"fontSize": "0.68rem"},
    )
    return html.Div(sentences + [footer])


def _tab_contexto_exterior(
    location_uuid: str | None,
    fmin_p: date,
    fecha_max: date,
    ventana: str,
    festivos: dict[date, str],
    fmin_sama: date,
    fmax_sama: date,
    fmin_msaa: date,
    fmax_msaa: date,
) -> html.Div:
    dias_v = 28 if ventana == "mes" else 7

    ap_act = _dias_apertura(fmin_p, fecha_max, festivos)
    ap_sa = _dias_apertura(fmin_sama, fmax_sama, festivos)
    ap_msa = _dias_apertura(fmin_msaa, fmax_msaa, festivos)

    sentences = [_sentence_dias_apertura(ap_act, dias_v, ap_sa, ap_msa, ventana)]

    if location_uuid:
        try:
            from src.db.queries import get_señal_diaria
            from src.db.store import get_conn

            available = {
                r[0]
                for r in get_conn()
                .execute(
                    "SELECT DISTINCT señal_id FROM valores_señales WHERE ubicacion_id = ?",
                    [location_uuid],
                )
                .fetchall()
            }

            for señal_id, _label, suffix, method in _SIGNAL_CFG:
                if señal_id not in available:
                    continue
                try:
                    s_act = get_señal_diaria(
                        location_uuid, señal_id, pd.Timestamp(fmin_p), pd.Timestamp(fecha_max)
                    )
                    s_sa = get_señal_diaria(
                        location_uuid,
                        señal_id,
                        pd.Timestamp(fmin_sama),
                        pd.Timestamp(fmax_sama),
                    )
                    s_msa = get_señal_diaria(
                        location_uuid,
                        señal_id,
                        pd.Timestamp(fmin_msaa),
                        pd.Timestamp(fmax_msaa),
                    )
                except Exception:
                    continue

                v_act = _agg_señal(s_act, method)
                v_sa = _agg_señal(s_sa, method)
                v_msa = _agg_señal(s_msa, method)
                if v_act is None:
                    continue

                sentences.append(
                    _sentence_señal(señal_id, v_act, suffix, method, v_sa, v_msa, ventana)
                )
        except Exception:
            pass

    # Calendar
    festivos_en_periodo = {d: n for d, n in festivos.items() if fmin_p <= d <= fecha_max}
    legend = html.Div(
        [
            html.Span("■ Festivo  ", style={"color": "#856404", "fontSize": "0.68rem"}),
            html.Span("■ Sábado  ", style={"color": "#6c757d", "fontSize": "0.68rem"}),
            html.Span("■ Domingo  ", style={"color": "#adb5bd", "fontSize": "0.68rem"}),
            html.Span("■ Laborable", style={"color": "#212529", "fontSize": "0.68rem"}),
        ]
    )
    festivos_list = (
        html.Div(
            [
                html.Span(
                    f"{d.strftime('%d/%m')}  {name}",
                    className="d-block",
                    style={"fontSize": "0.72rem", "color": "#856404"},
                )
                for d, name in sorted(festivos_en_periodo.items())
            ],
            className="mt-2",
        )
        if festivos_en_periodo
        else html.P(
            "Sin festivos en el período.",
            className="text-muted mt-2 mb-0",
            style={"fontSize": "0.72rem"},
        )
    )

    return html.Div(
        [
            html.Div(sentences),
            _sub_header("fas fa-calendar-alt", "Calendario del período", "#E67E22"),
            legend,
            _build_calendar(fmin_p, fecha_max, festivos),
            festivos_list,
        ]
    )


def _tab_contexto_interior(
    fmin_p: date,
    fecha_max: date,
    ventana: str,
    festivos: dict[date, str],
    fmin_sama: date,
    fmax_sama: date,
    fmin_msaa: date,
    fmax_msaa: date,
) -> html.Div:
    dias_v = 28 if ventana == "mes" else 7

    ap_act = _dias_apertura(fmin_p, fecha_max, festivos)
    ap_sa = _dias_apertura(fmin_sama, fmax_sama, festivos)
    ap_msa = _dias_apertura(fmin_msaa, fmax_msaa, festivos)

    placeholder = html.Div(
        html.P(
            "Próximamente: competencia, promociones activas, lanzamientos de producto.",
            className="text-muted fst-italic mb-0",
            style={"fontSize": "0.79rem"},
        ),
        className="p-3 rounded-3 mt-2",
        style={"backgroundColor": "#f8f9fa", "border": "1px dashed #dee2e6"},
    )

    return html.Div([_sentence_dias_apertura(ap_act, dias_v, ap_sa, ap_msa, ventana), placeholder])


# ── Public API ────────────────────────────────────────────────────────────────


def render_informe_tabs(
    location_uuid: str | None,
    zonas_data: list[dict],
    df: pd.DataFrame,
    fmin_p,
    fecha_max,
    ventana: str = "semana",
) -> dbc.Card:
    """
    3-tab informe card: Resumen · Contexto Exterior · Contexto Interior.
    Drop-in replacement for _correlacion_card in health_check.py.
    """
    fmin_p = _to_date(fmin_p)
    fecha_max = _to_date(fecha_max)

    dias_v = 28 if ventana == "mes" else 7
    fmin_sama = fmin_p - timedelta(days=dias_v)
    fmax_sama = fmin_p - timedelta(days=1)
    fmin_msaa = fmin_p - timedelta(days=364)
    fmax_msaa = fecha_max - timedelta(days=364)

    years = {fmin_p.year, fecha_max.year, fmin_msaa.year, fmax_msaa.year}
    pais_codigo, ciudad = _get_location_meta(location_uuid) if location_uuid else ("ES", "")
    festivos = _get_festivos(pais_codigo, ciudad, years)

    _lbl_style = {"fontSize": "0.81rem", "padding": "6px 10px"}
    _active_style = {"fontSize": "0.81rem", "padding": "6px 10px", "fontWeight": "600"}

    tabs = dbc.Tabs(
        [
            dbc.Tab(
                html.Div(
                    _tab_resumen(zonas_data, df, fmin_p, fecha_max, ventana),
                    style={"paddingTop": "10px"},
                ),
                label="Resumen",
                label_style=_lbl_style,
                active_label_style={**_active_style, "color": "#0052CC"},
            ),
            dbc.Tab(
                html.Div(
                    _tab_contexto_exterior(
                        location_uuid,
                        fmin_p,
                        fecha_max,
                        ventana,
                        festivos,
                        fmin_sama,
                        fmax_sama,
                        fmin_msaa,
                        fmax_msaa,
                    ),
                    style={"paddingTop": "10px"},
                ),
                label="Contexto exterior",
                label_style=_lbl_style,
                active_label_style={**_active_style, "color": "#E67E22"},
            ),
            dbc.Tab(
                html.Div(
                    _tab_contexto_interior(
                        fmin_p,
                        fecha_max,
                        ventana,
                        festivos,
                        fmin_sama,
                        fmax_sama,
                        fmin_msaa,
                        fmax_msaa,
                    ),
                    style={"paddingTop": "10px"},
                ),
                label="Contexto interior",
                label_style=_lbl_style,
                active_label_style={**_active_style, "color": "#8E44AD"},
            ),
        ],
    )

    return dbc.Card(
        dbc.CardBody(
            [
                html.H6(
                    [
                        html.I(className="fas fa-chart-line me-2 text-primary"),
                        "Informe de período",
                    ],
                    className="fw-bold mb-2",
                    style={"fontSize": "0.92rem", "color": "#2c3e50"},
                ),
                tabs,
            ]
        ),
        className="border-0 shadow-sm rounded-4 h-100",
    )
