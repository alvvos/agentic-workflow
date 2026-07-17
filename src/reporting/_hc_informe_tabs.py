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
_ZONE_LABEL_SHORT = {0: "Caja / Checkout", 1: "Interior (tienda)", 2: "Exterior (calle)"}
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
_DIA_NAMES_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# ── Typography & color tokens ────────────────────────────────────────────────
_C_PROSE = "#495057"
_C_VAL = "#1e293b"  # bold KPI values
_C_REF = "#9ca3af"  # small reference values in parentheses
_C_POS = "#16a34a"  # positive diff
_C_NEG = "#dc2626"  # negative diff
_C_NEU = "#6b7280"  # neutral / equal

_SZ_PROSE = "0.95rem"
_SZ_VAL = "1.13rem"
_SZ_REF = "0.84rem"


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


# ── Span builders ────────────────────────────────────────────────────────────


def _t(text: str) -> html.Span:
    return html.Span(text, style={"color": _C_PROSE})


def _bold(text: str, color: str = _C_VAL, size: str = _SZ_VAL) -> html.Span:
    return html.Span(text, style={"fontWeight": "700", "fontSize": size, "color": color})


def _diff_span(text: str, positive: bool | None) -> html.Span:
    color = _C_POS if positive is True else _C_NEG if positive is False else _C_NEU
    return html.Span(text, style={"fontWeight": "700", "color": color})


def _ref(text: str) -> html.Span:
    return html.Span(text, style={"color": _C_REF, "fontSize": _SZ_REF})


def _sp(children: list) -> html.P:
    return html.P(
        children,
        style={
            "fontSize": _SZ_PROSE,
            "marginBottom": "10px",
            "lineHeight": "1.75",
            "color": _C_PROSE,
        },
    )


# ── Kendall's τ (pure numpy + math, no scipy) ────────────────────────────────


def _kendall_tau_np(x, y) -> tuple[float, float]:
    """Kendall's τ_b and asymptotic p-value without scipy."""
    import math

    import numpy as np

    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(x)
    if n < 10:
        return 0.0, 1.0
    c = d = tx = ty = 0
    for i in range(n - 1):
        dx = x[i] - x[i + 1 :]
        dy = y[i] - y[i + 1 :]
        prod = dx * dy
        c += int((prod > 0).sum())
        d += int((prod < 0).sum())
        tx += int((dx == 0).sum())
        ty += int((dy == 0).sum())
    pairs = n * (n - 1) // 2
    denom = math.sqrt((pairs - tx) * (pairs - ty))
    tau = (c - d) / denom if denom > 0 else 0.0
    sigma = math.sqrt(2 * (2 * n + 5) / (9 * n * (n - 1)))
    z = tau / sigma if sigma > 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return tau, p


def _impacto_badge(
    señal_id: str,
    location_uuid: str,
    df: pd.DataFrame,
    fmin_hist: date,
    fecha_max: date,
) -> html.Span | None:
    """Badge showing Kendall's τ correlation between signal and visitor counts."""
    try:
        from src.db.queries import get_señal_diaria

        s = get_señal_diaria(
            location_uuid, señal_id, pd.Timestamp(fmin_hist), pd.Timestamp(fecha_max)
        )
        if s is None or s.empty:
            return None
        v_daily = df.groupby("fecha_dt")["unique_visitors"].sum()
        if v_daily.empty:
            return None
        v_daily.index = pd.to_datetime(v_daily.index)
        s.index = pd.to_datetime(s.index)
        merged = pd.DataFrame({"s": s, "v": v_daily}).dropna()
        if len(merged) < 10:
            return None
        tau, p = _kendall_tau_np(merged["s"].to_numpy(), merged["v"].to_numpy())
        abs_tau = abs(tau)
        if p > 0.1 or abs_tau < 0.1:
            label, color, bg, border = "Sin impacto", "#9ca3af", "#f9fafb", "#e5e7eb"
        elif abs_tau < 0.25:
            label, color, bg, border = "Impacto leve", "#6b7280", "#f3f4f6", "#d1d5db"
        elif abs_tau < 0.45:
            label, color, bg, border = "Impacto moderado", "#b45309", "#fffbeb", "#fcd34d"
        else:
            label, color, bg, border = "Impacto alto", "#dc2626", "#fef2f2", "#fca5a5"
        tau_sign = "+" if tau >= 0 else "−"
        tau_str = f"τb = {tau_sign}{abs_tau:.2f}"
        if p < 0.001:
            p_str = "p < 0,001"
        elif p < 0.01:
            p_str = "p < 0,01"
        elif p < 0.05:
            p_str = "p < 0,05"
        elif p < 0.1:
            p_str = "p < 0,1"
        else:
            p_str = f"p = {p:.2f}"
        return html.Div(
            [
                html.Span(
                    label,
                    style={
                        "fontSize": "0.78rem",
                        "fontWeight": "700",
                        "color": color,
                        "display": "block",
                        "letterSpacing": "0.2px",
                    },
                ),
                html.Span(
                    f"{tau_str} \xb7 {p_str}",
                    style={
                        "fontSize": "0.68rem",
                        "color": color,
                        "opacity": "0.8",
                        "display": "block",
                        "marginTop": "1px",
                        "fontVariantNumeric": "tabular-nums",
                    },
                ),
            ],
            style={
                "backgroundColor": bg,
                "border": f"1px solid {border}",
                "borderRadius": "8px",
                "padding": "5px 10px",
                "whiteSpace": "nowrap",
                "textAlign": "center",
                "minWidth": "110px",
            },
        )
    except Exception:
        return None


# ── Sentence composition ─────────────────────────────────────────────────────


def _periodo_labels(ventana: str) -> tuple[str, str, str]:
    """(per_act_lower, lbl_sa, lbl_msa) — lowercase, ready for composition."""
    if ventana == "mes":
        return (
            "en el período analizado",
            "el período anterior",
            "el mismo período del año pasado",
        )
    return "esta semana", "la semana anterior", "la misma semana del año pasado"


def _diff_spans(
    diff: float | int | None,
    ref_str: str | None,
    lbl: str,
    suffix: str = "",
    decimals: int = 0,
    ref_num: float | int | None = None,
) -> list:
    """Span list for one comparison clause, empty if no data."""
    if diff is None or ref_str is None:
        return []
    if diff == 0:
        return [_t(f"igual que {lbl} "), _ref(f"({ref_str})")]
    is_pos = diff > 0
    more = "más" if is_pos else "menos"
    abs_d = abs(diff)
    d_str = f"{abs_d:.{decimals}f}{suffix}" if decimals > 0 else f"{int(round(abs_d))}{suffix}"
    pct_part = ""
    if ref_num is not None and ref_num != 0:
        pct = abs_d / abs(ref_num) * 100
        sign = "+" if is_pos else "−"
        pct_part = f" ({sign}{pct:.1f}%)"
    return [
        _diff_span(f"{d_str} {more}{pct_part}", positive=is_pos),
        _t(f" que {lbl} "),
        _ref(f"({ref_str})"),
    ]


def _assemble(inicio: list, sa: list, msa: list) -> list:
    """Combine inicio spans with up to two comparison clauses."""
    children = list(inicio)
    clauses = [c for c in [sa, msa] if c]
    if clauses:
        children.append(_t(", "))
        children.extend(clauses[0])
        if len(clauses) > 1:
            children.append(_t(" y "))
            children.extend(clauses[1])
    children.append(_t("."))
    return children


# ── Per-signal sentence builders ─────────────────────────────────────────────


def _sentence_visitantes(
    zone_enum: int,
    vis: int,
    vis_sa: int | None,
    vis_msa: int | None,
    ventana: str,
) -> html.P:
    per, lbl_sa, lbl_msa = _periodo_labels(ventana)
    sujeto = _ZONE_LABEL_FORMAL.get(zone_enum, "La zona")
    color = _ZONE_COLOR.get(zone_enum, _C_VAL)
    vis_str = f"{vis:,}".replace(",", ".")
    ref_sa = f"{vis_sa:,}".replace(",", ".") if vis_sa is not None else None
    ref_msa = f"{vis_msa:,}".replace(",", ".") if vis_msa is not None else None
    diff_sa = vis - vis_sa if vis_sa is not None else None
    diff_msa = vis - vis_msa if vis_msa is not None else None

    inicio = [_t(f"{sujeto} registró "), _bold(vis_str, color=color), _t(f" visitantes {per}")]
    return _sp(
        _assemble(
            inicio,
            _diff_spans(diff_sa, ref_sa, lbl_sa, ref_num=vis_sa),
            _diff_spans(diff_msa, ref_msa, lbl_msa, ref_num=vis_msa),
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
    diff_sa = ap_act - ap_sa
    diff_msa = ap_act - ap_msa

    inicio = [
        _t(f"{per_cap} hubo "),
        _bold(f"{ap_act} de {dias_v}"),
        _t(" días de apertura posibles"),
    ]
    return _sp(
        _assemble(
            inicio,
            _diff_spans(diff_sa, str(ap_sa), lbl_sa),
            _diff_spans(diff_msa, str(ap_msa), lbl_msa),
        )
    )


def _sentence_señal(
    señal_id: str,
    val_act: float | int,
    suffix: str,
    method: str,
    val_sa: float | int | None,
    val_msa: float | int | None,
    ventana: str,
) -> html.P:
    per, lbl_sa, lbl_msa = _periodo_labels(ventana)
    per_cap = per[0].upper() + per[1:]
    decimals = 1 if method == "mean" else 0
    diff_suffix = suffix if method == "mean" else ""
    ref_suffix = suffix if method == "mean" else ""

    # Build inicio spans (varies per signal)
    if señal_id == "llueve":
        if val_act == 0:
            inicio: list = [_t(f"{per_cap} no llovió")]
        elif val_act == 1:
            inicio = [_t(f"{per_cap} llovió "), _bold("un"), _t(" día")]
        else:
            inicio = [_t(f"{per_cap} llovió "), _bold(str(int(val_act))), _t(" días")]

    elif señal_id == "temp_max":
        inicio = [
            _t("La temperatura máxima media fue de "),
            _bold(_fmt_val(val_act, suffix, method)),
            _t(f" {per}"),
        ]

    elif señal_id == "temp_min":
        inicio = [
            _t("La temperatura mínima media fue de "),
            _bold(_fmt_val(val_act, suffix, method)),
            _t(f" {per}"),
        ]

    elif señal_id == "escala_crucero":
        if val_act == 0:
            inicio = [_t(f"{per_cap} no hubo escalas de crucero")]
        elif val_act == 1:
            inicio = [_t(f"{per_cap} se registró "), _bold("una"), _t(" escala de crucero")]
        else:
            inicio = [
                _t(f"{per_cap} se registraron "),
                _bold(str(int(val_act))),
                _t(" escalas de crucero"),
            ]

    elif señal_id == "n_pasajeros_crucero_dia":
        inicio = [
            _t("El volumen estimado de pasajeros de crucero fue de "),
            _bold(_fmt_val(val_act, "", "sum_int")),
            _t(f" {per}"),
        ]

    elif señal_id == "n_pasajeros_crucero_oficial":
        inicio = [
            _t("El volumen oficial de pasajeros de crucero fue de "),
            _bold(_fmt_val(val_act, "", "sum_int")),
            _t(f" {per}"),
        ]

    else:
        inicio = [_bold(_fmt_val(val_act, suffix, method)), _t(f" {per}")]

    ref_sa = _fmt_val(val_sa, ref_suffix, method) if val_sa is not None else None
    ref_msa = _fmt_val(val_msa, ref_suffix, method) if val_msa is not None else None
    diff_sa = float(val_act) - float(val_sa) if val_sa is not None else None
    diff_msa = float(val_act) - float(val_msa) if val_msa is not None else None

    return _sp(
        _assemble(
            inicio,
            _diff_spans(
                diff_sa, ref_sa, lbl_sa, suffix=diff_suffix, decimals=decimals, ref_num=val_sa
            ),
            _diff_spans(
                diff_msa, ref_msa, lbl_msa, suffix=diff_suffix, decimals=decimals, ref_num=val_msa
            ),
        )
    )


# ── Zone header ──────────────────────────────────────────────────────────────


def _zone_header(zone_enum: int) -> html.Div:
    label = _ZONE_LABEL_SHORT.get(zone_enum, "Subzona")
    icon = _ZONE_ICON.get(zone_enum, "fas fa-layer-group")
    color = _ZONE_COLOR.get(zone_enum, "#6c757d")
    return html.Div(
        [
            html.I(className=f"{icon} me-2", style={"color": color, "fontSize": "0.75rem"}),
            html.Span(
                label.upper(),
                style={
                    "fontSize": "0.68rem",
                    "fontWeight": "700",
                    "color": color,
                    "letterSpacing": "0.8px",
                },
            ),
        ],
        className="mb-1 mt-3",
    )


# ── Sub-section header ───────────────────────────────────────────────────────


def _sub_header(icon_cls: str, text: str, color: str) -> html.Div:
    return html.Div(
        [
            html.I(className=f"{icon_cls} me-2", style={"color": color, "fontSize": "0.78rem"}),
            html.Span(
                text,
                style={"fontWeight": "600", "fontSize": "0.85rem", "color": "#343a40"},
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
                    "fontSize": "0.69rem",
                    "textAlign": "center",
                    "color": "#dc3545" if i >= 5 else "#6c757d",
                    "padding": "2px 4px",
                    "fontWeight": "700",
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
                bg, color, fw, border = "#fff3cd", "#856404", "700", "1px solid #ffc107"
            elif is_sunday:
                bg, color, fw, border = "#f8f9fa", "#adb5bd", "normal", "1px solid #e9ecef"
            elif is_saturday:
                bg, color, fw, border = "#f0f4fb", "#6c757d", "normal", "1px solid #e9ecef"
            else:
                bg, color, fw, border = "#ffffff", "#212529", "normal", "1px solid #e9ecef"

            festivo_name = festivos.get(d, "")
            children: list = [
                html.Span(
                    str(d.day), style={"display": "block", "fontWeight": fw, "fontSize": "0.8rem"}
                )
            ]
            if festivo_name and in_period:
                short = festivo_name.split("(")[0].strip()
                if len(short) > 12:
                    short = short[:11] + "…"
                children.append(
                    html.Span(
                        short,
                        style={
                            "fontSize": "0.52rem",
                            "display": "block",
                            "lineHeight": "1.15",
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
                        "padding": "4px 2px",
                        "backgroundColor": bg,
                        "color": color,
                        "borderRadius": "5px",
                        "minWidth": "36px",
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
                "borderSpacing": "3px",
                "tableLayout": "fixed",
            },
        ),
        style={"overflowX": "auto", "marginTop": "8px"},
    )


# ── Resumen: narrative callout + KPI list ────────────────────────────────────


def _build_by_enum(
    zonas_data: list[dict],
    df: pd.DataFrame | None,
    fmin_msaa: date,
    fmax_msaa: date,
) -> dict[int, dict]:
    """Aggregate zonas_data into {zone_enum: metrics_dict} with SA, MSAA and dwell."""
    by_enum: dict[int, dict] = {}
    for z in zonas_data:
        ze = z.get("zone_enum")
        if ze is None or ze not in (0, 1, 2):
            continue
        grp = by_enum.setdefault(
            ze,
            dict(
                zona_names=[],
                vis_act=0,
                vis_sa=0,
                vis_msa=0,
                est_sum=0.0,
                est_cnt=0,
                est_sa_sum=0.0,
                est_sa_cnt=0,
                dias_p_list=[],
            ),
        )
        grp["zona_names"].append(z["zona"])
        grp["vis_act"] += z["r"].get("visitantes", 0)
        grp["vis_sa"] += z["a"].get("visitantes", 0)
        est = z["r"].get("estancia", 0)
        if est > 0:
            grp["est_sum"] += est
            grp["est_cnt"] += 1
        est_a = z["a"].get("estancia", 0)
        if est_a > 0:
            grp["est_sa_sum"] += est_a
            grp["est_sa_cnt"] += 1
        dias = z.get("dias_p")
        if dias is not None and not dias.empty and "unique_visitors" in dias.columns:
            grp["dias_p_list"].append(dias)

    if df is not None and not df.empty and "unique_visitors" in df.columns and "Zona" in df.columns:
        for grp in by_enum.values():
            mask = (
                df["Zona"].isin(grp["zona_names"])
                & (df["fecha_dt"] >= fmin_msaa)
                & (df["fecha_dt"] <= fmax_msaa)
            )
            grp["vis_msa"] = int(df.loc[mask, "unique_visitors"].sum())

    for grp in by_enum.values():
        v, vs, vm = grp["vis_act"], grp["vis_sa"], grp["vis_msa"]
        grp["d_sa"] = ((v - vs) / vs * 100) if vs > 0 else None
        grp["d_msa"] = ((v - vm) / vm * 100) if vm > 0 else None
        grp["est_mean"] = grp["est_sum"] / grp["est_cnt"] if grp["est_cnt"] > 0 else 0.0
        grp["est_sa_mean"] = grp["est_sa_sum"] / grp["est_sa_cnt"] if grp["est_sa_cnt"] > 0 else 0.0

    return by_enum


def _narrative_block(by_enum: dict[int, dict], ventana: str) -> html.Div:
    """Blue callout box with 2-3 interpretive sentences at the top of Resumen."""
    per, lbl_sa, _ = _periodo_labels(ventana)
    per_cap = per[0].upper() + per[1:]

    ext = by_enum.get(2)
    int_ = by_enum.get(1)

    parts: list[str] = []

    # Overall assessment
    deltas = [grp["d_sa"] for grp in by_enum.values() if grp["d_sa"] is not None]
    if deltas:
        n_pos = sum(1 for d in deltas if d > 5)
        n_neg = sum(1 for d in deltas if d < -5)

        if ext and int_ and ext["d_sa"] is not None and int_["d_sa"] is not None:
            gap = ext["d_sa"] - int_["d_sa"]
            if ext["d_sa"] > 10 and gap > 15:
                parts.append(
                    "Buen crecimiento de tráfico exterior aunque no se ha podido captar todo"
                    " su potencial en tienda. Recomendación: revisar los elementos de conversión de calle a tienda."
                )
            elif n_pos == len(deltas):
                parts.append(f"{per_cap} positiva con crecimiento en todas las zonas.")
            elif n_neg == len(deltas):
                parts.append(f"{per_cap} de menor tráfico en todas las zonas respecto a {lbl_sa}.")
            elif n_pos > n_neg:
                parts.append(f"{per_cap} con tendencia positiva en la mayoría de zonas.")
            else:
                parts.append(f"{per_cap} con tendencia mixta por zona.")
        elif n_pos == len(deltas):
            parts.append(f"{per_cap} positiva con crecimiento en todas las zonas.")
        elif n_neg == len(deltas):
            parts.append(f"{per_cap} de menor tráfico respecto a {lbl_sa}.")
        else:
            parts.append(f"{per_cap} con tendencia mixta por zona.")

    # Dwell time comment
    dwell_grp = int_ or (next(iter(by_enum.values()), None) if by_enum else None)
    if dwell_grp:
        est = dwell_grp["est_mean"]
        est_sa = dwell_grp["est_sa_mean"]
        if est > 0 and est_sa > 0:
            diff = est - est_sa
            if abs(diff) >= 0.5:
                direction = "aumentado" if diff > 0 else "reducido"
                parts.append(
                    f"El tiempo en tienda se ha {direction} en {abs(diff):.1f} min respecto a {lbl_sa}."
                )

    # Conversion ratio trend
    if ext and int_ and ext["vis_sa"] > 0 and int_["vis_sa"] > 0 and ext["vis_act"] > 0:
        ratio_act = int_["vis_act"] / ext["vis_act"] * 100
        ratio_sa = int_["vis_sa"] / ext["vis_sa"] * 100
        diff_r = ratio_act - ratio_sa
        if diff_r <= -3:
            parts.append(
                f"El ratio de conversión del exterior a la tienda ha caído {abs(diff_r):.1f}pp"
                f" ({ratio_act:.0f}% vs {ratio_sa:.0f}% en {lbl_sa})."
            )
        elif diff_r >= 3:
            parts.append(
                f"El ratio de conversión del exterior a la tienda ha mejorado {diff_r:.1f}pp"
                f" ({ratio_act:.0f}% vs {ratio_sa:.0f}% en {lbl_sa})."
            )

    if not parts:
        return html.Div()

    return html.Div(
        html.P(
            " ".join(parts),
            style={
                "fontSize": _SZ_PROSE,
                "marginBottom": "0",
                "lineHeight": "1.7",
                "color": "#1e293b",
            },
        ),
        style={
            "backgroundColor": "#f0f4fb",
            "borderLeft": "3px solid #0052CC",
            "borderRadius": "0 6px 6px 0",
            "padding": "10px 14px",
            "marginBottom": "16px",
        },
    )


def _analysis_sentences(
    by_enum: dict[int, dict],
    df: pd.DataFrame,
    fmin_p: date,
    fecha_max: date,
    ventana: str,
) -> html.Div:
    """Prose sentences for dwell time, peak day/hour, new visitors, and frequency."""
    import json as _json

    _, lbl_sa, _ = _periodo_labels(ventana)
    int_ = by_enum.get(1)
    sentences: list = []

    # Dwell time
    dwell_grp = int_ or (next(iter(by_enum.values()), None) if by_enum else None)
    if dwell_grp and dwell_grp["est_mean"] > 0:
        est = dwell_grp["est_mean"]
        est_sa = dwell_grp["est_sa_mean"]
        est_str = f"{est:.1f} min"
        if est_sa > 0:
            diff = est - est_sa
            sign = "+" if diff >= 0 else ""
            est_str += f" ({sign}{diff:.1f} min vs {lbl_sa})"
        sentences.append(html.Li(f"Estancia media en tienda: {est_str}."))

    # Peak weekday
    try:
        all_dias = [d for grp in by_enum.values() for d in grp.get("dias_p_list", [])]
        if all_dias:
            combined = pd.concat(all_dias, ignore_index=True)
            combined["wd"] = pd.to_datetime(combined["fecha_dt"]).dt.dayofweek
            by_day = (
                combined.groupby(["fecha_dt", "wd"])["unique_visitors"]
                .sum()
                .reset_index()
                .groupby("wd")["unique_visitors"]
                .mean()
            )
            if len(by_day) >= 3:
                dia_max = int(by_day.idxmax())
                dia_min = int(by_day.idxmin())
                txt = f"Día de mayor afluencia: {_DIA_NAMES_ES[dia_max].capitalize()}"
                if dia_max != dia_min:
                    txt += f" (menor: {_DIA_NAMES_ES[dia_min]})"
                sentences.append(html.Li(txt + "."))
    except Exception:
        pass

    # Peak hour
    if not df.empty and "hourly_visits" in df.columns:
        try:
            df_p = df[(df["fecha_dt"] >= fmin_p) & (df["fecha_dt"] <= fecha_max)]
            hourly: dict[int, float] = {}
            for val in df_p["hourly_visits"].dropna():
                try:
                    h_dict = _json.loads(val) if isinstance(val, str) else (val or {})
                    for h, v in h_dict.items():
                        k = int(h)
                        hourly[k] = hourly.get(k, 0.0) + (float(v) if v else 0.0)
                except Exception:
                    pass
            if hourly:
                hp = max(hourly, key=lambda h: hourly[h])
                sentences.append(
                    html.Li(
                        f"La hora de mayor afluencia se sitúa entre las {hp:02d}:00 y las {hp + 1:02d}:00."
                    )
                )
        except Exception:
            pass

    # New-visitor ratio
    if not df.empty and "new_visitors" in df.columns and "unique_visitors" in df.columns:
        try:
            df_p = df[(df["fecha_dt"] >= fmin_p) & (df["fecha_dt"] <= fecha_max)]
            total_new = df_p["new_visitors"].sum()
            total_uv = df_p["unique_visitors"].sum()
            if total_uv > 0 and total_new > 0:
                pct_new = total_new / total_uv * 100
                if pct_new >= 60:
                    perfil = "perfil de alta atracción"
                elif pct_new >= 35:
                    perfil = "equilibrio entre nuevos y recurrentes"
                else:
                    perfil = "base recurrente consolidada"
                sentences.append(
                    html.Li(
                        f"El {pct_new:.0f}% de los visitantes son nuevos, lo que indica {perfil}."
                    )
                )
        except Exception:
            pass

    # Frequency
    freq_col = "freq_28d" if (fecha_max - fmin_p).days > 10 else "freq_7d"
    if not df.empty and freq_col in df.columns:
        try:
            df_p = df[(df["fecha_dt"] >= fmin_p) & (df["fecha_dt"] <= fecha_max)]
            freq_mean = df_p[freq_col].replace(0, pd.NA).mean()
            if pd.notna(freq_mean) and freq_mean > 1.05:
                sentences.append(
                    html.Li(f"Frecuencia media: {freq_mean:.1f} visitas por visitante único.")
                )
        except Exception:
            pass

    if not sentences:
        return html.Div()

    return html.Div(
        [
            _sub_header("fas fa-chart-bar", "Análisis del período", "#0052CC"),
            html.Ul(
                sentences,
                style={
                    "fontSize": _SZ_PROSE,
                    "lineHeight": "1.8",
                    "paddingLeft": "18px",
                    "marginBottom": "0",
                },
            ),
        ],
        style={"marginTop": "8px"},
    )


# ── Tab content builders ──────────────────────────────────────────────────────


def _visitor_blocks(
    zonas_data: list[dict],
    zone_filter: set[int],
    df: pd.DataFrame | None,
    fmin_msaa: date,
    fmax_msaa: date,
    ventana: str,
) -> list:
    """Visitor-count header + sentence blocks for the requested zone_enums."""
    by_enum: dict[int, dict] = {}
    for z in zonas_data:
        ze = z.get("zone_enum")
        if ze is None or ze not in zone_filter:
            continue
        if ze not in by_enum:
            by_enum[ze] = {"zona_names": [], "vis_act": 0, "vis_sama": 0, "vis_msaa": 0}
        by_enum[ze]["zona_names"].append(z["zona"])
        by_enum[ze]["vis_act"] += z["r"].get("visitantes", 0)
        by_enum[ze]["vis_sama"] += z["a"].get("visitantes", 0)

    if df is not None and not df.empty and "unique_visitors" in df.columns and "Zona" in df.columns:
        for grp in by_enum.values():
            mask = (
                df["Zona"].isin(grp["zona_names"])
                & (df["fecha_dt"] >= fmin_msaa)
                & (df["fecha_dt"] <= fmax_msaa)
            )
            grp["vis_msaa"] = int(df.loc[mask, "unique_visitors"].sum())

    blocks = []
    for ze in sorted(by_enum.keys(), reverse=True):  # higher enum first (exterior before interior)
        grp = by_enum[ze]
        vis = grp["vis_act"]
        vis_sa = grp["vis_sama"] if grp["vis_sama"] > 0 else None
        vis_msa = grp["vis_msaa"] if grp["vis_msaa"] > 0 else None
        blocks.append(_zone_header(ze))
        blocks.append(_sentence_visitantes(ze, vis, vis_sa, vis_msa, ventana))
    return blocks


def _tab_resumen(
    zonas_data: list[dict],
    df: pd.DataFrame,
    fmin_p: date,
    fecha_max: date,
    ventana: str,
) -> html.Div:
    fmin_msaa = fmin_p - timedelta(days=364)
    fmax_msaa = fecha_max - timedelta(days=364)
    by_enum = _build_by_enum(zonas_data, df, fmin_msaa, fmax_msaa)
    if not by_enum:
        return html.P("Sin datos de zona disponibles.", className="text-muted small")
    narrative = _narrative_block(by_enum, ventana)
    vis_blocks = _visitor_blocks(zonas_data, {0, 1, 2}, df, fmin_msaa, fmax_msaa, ventana)
    analysis = _analysis_sentences(by_enum, df, fmin_p, fecha_max, ventana)
    return html.Div([narrative] + vis_blocks + [analysis])


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
    df: pd.DataFrame | None = None,
    zonas_data: list[dict] | None = None,
) -> html.Div:
    dias_v = 28 if ventana == "mes" else 7

    ap_act = _dias_apertura(fmin_p, fecha_max, festivos)
    ap_sa = _dias_apertura(fmin_sama, fmax_sama, festivos)
    ap_msa = _dias_apertura(fmin_msaa, fmax_msaa, festivos)

    # ── Tráfico exterior ──────────────────────────────────────────────────────
    traffic = (
        _visitor_blocks(zonas_data, {2}, df, fmin_msaa, fmax_msaa, ventana) if zonas_data else []
    )

    # ── Señales externas + días apertura ─────────────────────────────────────
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
                        location_uuid, señal_id, pd.Timestamp(fmin_sama), pd.Timestamp(fmax_sama)
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

                sentence = _sentence_señal(señal_id, v_act, suffix, method, v_sa, v_msa, ventana)
                badge = (
                    _impacto_badge(señal_id, location_uuid, df, fmin_msaa, fecha_max)
                    if df is not None and not df.empty
                    else None
                )
                block = html.Div(
                    [
                        html.Div(sentence, style={"flex": "1", "minWidth": "0"}),
                        (
                            html.Div(
                                badge,
                                style={
                                    "flexShrink": "0",
                                    "paddingTop": "1px",
                                    "paddingLeft": "12px",
                                },
                            )
                            if badge
                            else None
                        ),
                    ],
                    style={"display": "flex", "alignItems": "flex-start", "marginBottom": "2px"},
                )
                sentences.append(block)
        except Exception:
            pass

    # Calendar
    festivos_en_periodo = {d: n for d, n in festivos.items() if fmin_p <= d <= fecha_max}
    legend = html.Div(
        [
            html.Span("■ Festivo  ", style={"color": "#856404", "fontSize": "0.72rem"}),
            html.Span("■ Sábado  ", style={"color": "#6c757d", "fontSize": "0.72rem"}),
            html.Span("■ Domingo  ", style={"color": "#adb5bd", "fontSize": "0.72rem"}),
            html.Span("■ Laborable", style={"color": "#495057", "fontSize": "0.72rem"}),
        ]
    )
    festivos_list = (
        html.Div(
            [
                html.Span(
                    f"{d.strftime('%d/%m')}  {name}",
                    className="d-block",
                    style={"fontSize": "0.76rem", "color": "#856404"},
                )
                for d, name in sorted(festivos_en_periodo.items())
            ],
            className="mt-2",
        )
        if festivos_en_periodo
        else html.P(
            "Sin festivos en el período.",
            className="text-muted mt-2 mb-0",
            style={"fontSize": "0.76rem"},
        )
    )

    señales_header = (
        [_sub_header("fas fa-cloud-sun", "Señales externas", "#E67E22")]
        if sentences and traffic
        else []
    )

    return html.Div(
        traffic
        + señales_header
        + [html.Div(sentences)]
        + [
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
    zonas_data: list[dict] | None = None,
    df: pd.DataFrame | None = None,
) -> html.Div:
    dias_v = 28 if ventana == "mes" else 7

    ap_act = _dias_apertura(fmin_p, fecha_max, festivos)
    ap_sa = _dias_apertura(fmin_sama, fmax_sama, festivos)
    ap_msa = _dias_apertura(fmin_msaa, fmax_msaa, festivos)

    # ── Tráfico interior: tienda (1) y caja (0) por separado ─────────────────
    traffic = (
        _visitor_blocks(zonas_data, {0, 1}, df, fmin_msaa, fmax_msaa, ventana) if zonas_data else []
    )

    placeholder = html.Div(
        html.P(
            "Próximamente: competencia, promociones activas, lanzamientos de producto.",
            className="text-muted fst-italic mb-0",
            style={"fontSize": "0.82rem"},
        ),
        className="p-3 rounded-3 mt-3",
        style={"backgroundColor": "#f8f9fa", "border": "1px dashed #dee2e6"},
    )

    return html.Div(
        traffic + [_sentence_dias_apertura(ap_act, dias_v, ap_sa, ap_msa, ventana), placeholder]
    )


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

    _lbl_style = {"fontSize": "0.83rem", "padding": "7px 12px"}
    _active_style = {"fontSize": "0.83rem", "padding": "7px 12px", "fontWeight": "600"}

    tabs = dbc.Tabs(
        [
            dbc.Tab(
                html.Div(
                    _tab_resumen(zonas_data, df, fmin_p, fecha_max, ventana),
                    style={"paddingTop": "12px"},
                ),
                label="Resumen",
                tab_id="resumen",
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
                        df=df,
                        zonas_data=zonas_data,
                    ),
                    style={"paddingTop": "12px"},
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
                        zonas_data=zonas_data,
                        df=df,
                    ),
                    style={"paddingTop": "12px"},
                ),
                label="Contexto interior",
                label_style=_lbl_style,
                active_label_style={**_active_style, "color": "#8E44AD"},
            ),
        ],
        active_tab="resumen",
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
                    style={"fontSize": "0.94rem", "color": "#1e293b"},
                ),
                tabs,
            ]
        ),
        className="border-0 shadow-sm rounded-4 h-100",
    )
