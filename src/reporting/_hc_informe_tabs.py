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

# señal_id → (display_label, unit_suffix, agg_method)
_SIGNAL_REGISTRY: dict[str, tuple[str, str, str]] = {
    "llueve": ("Días con lluvia", " días", "count_positive"),
    "temp_max": ("Temperatura máx. media", "°C", "mean"),
    "temp_min": ("Temperatura mín. media", "°C", "mean"),
    "escala_crucero": ("Escalas de crucero", "", "count_positive"),
    "n_pasajeros_crucero_dia": ("Pasajeros crucero (est.)", "", "sum_int"),
    "n_pasajeros_crucero_oficial": ("Pasajeros crucero (of.)", "", "sum_int"),
    "n_eventos_culturales_dia": ("Eventos culturales", "", "sum_int"),
    "eoh_viajeros_total": ("Viajeros hoteleros (mes)", "", "monthly_value"),
    "eoh_pernoctaciones_total": ("Pernoctaciones hoteleras (mes)", "", "monthly_value"),
    "egatur_gasto_medio_diario": ("Gasto diario turista intl.", "€/día", "mean"),
    "egatur_duracion_media_viaje": ("Duración media viaje turista intl.", " días", "mean"),
}

# agg function for _render_signal_yoy_chart; exported to health_check city-chart auto-renderer
_METHOD_TO_AGG: dict[str, str] = {
    "monthly_value": "max",
    "mean": "mean",
    "sum_int": "sum",
    "count_positive": "sum",
}


def _get_context_signals(location_uuid: str, include_active: bool = False) -> list[str]:
    """
    Devuelve las señales de contexto de una ubicación ordenadas por `orden`.

    include_active=True  → incluye señales con status 'active' (clima) además de 'contexto'.
    include_active=False → solo señales con status='contexto' (señales ciudad-específicas).
    """
    try:
        from src.db.store import get_conn

        if include_active:
            rows = (
                get_conn()
                .execute(
                    "SELECT señal_id FROM activacion_señales "
                    "WHERE ubicacion_id = ? AND status != 'inactive' "
                    "ORDER BY orden, señal_id",
                    [location_uuid],
                )
                .fetchall()
            )
        else:
            rows = (
                get_conn()
                .execute(
                    "SELECT señal_id FROM activacion_señales "
                    "WHERE ubicacion_id = ? AND status = 'contexto' "
                    "ORDER BY orden, señal_id",
                    [location_uuid],
                )
                .fetchall()
            )
        return [r[0] for r in rows]
    except Exception:
        return []


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
    if method == "monthly_value":
        v = serie[serie > 0]
        return int(v.max()) if not v.empty else None
    return None


def _fmt_val(val: float | int | None, suffix: str, method: str) -> str:
    if val is None:
        return "s/d"
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


def _mann_whitney_np(group0, group1) -> tuple[float, float]:
    """Rank-biserial r and asymptotic p-value for two independent groups (no scipy)."""
    import math

    import numpy as np

    g0 = np.asarray(group0, dtype=float)
    g1 = np.asarray(group1, dtype=float)
    n0, n1 = len(g0), len(g1)
    if n0 < 5 or n1 < 5:
        return 0.0, 1.0
    comp = g1[:, None] - g0[None, :]  # (n1, n0) signed differences
    u1 = float(np.sum(comp > 0) + 0.5 * np.sum(comp == 0))
    u2 = n0 * n1 - u1
    r = (u1 - u2) / (n0 * n1)  # rank-biserial correlation, signed
    mu = n0 * n1 / 2.0
    sigma = math.sqrt(n0 * n1 * (n0 + n1 + 1) / 12.0)
    z = (min(u1, u2) - mu) / sigma if sigma > 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return r, p


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

        is_binary = merged["s"].nunique() <= 2
        if is_binary:
            g0 = merged.loc[merged["s"] == 0, "v"].to_numpy()
            g1 = merged.loc[merged["s"] != 0, "v"].to_numpy()
            effect, p = _mann_whitney_np(g0, g1)
            stat_label = "r"
        else:
            effect, p = _kendall_tau_np(merged["s"].to_numpy(), merged["v"].to_numpy())
            stat_label = "τb"

        abs_effect = abs(effect)
        if p > 0.1 or abs_effect < 0.1:
            label, color, bg, border = "Sin impacto", "#9ca3af", "#f9fafb", "#e5e7eb"
        elif abs_effect < 0.25:
            label, color, bg, border = "Impacto leve", "#6b7280", "#f3f4f6", "#d1d5db"
        elif abs_effect < 0.45:
            label, color, bg, border = "Impacto moderado", "#b45309", "#fffbeb", "#fcd34d"
        else:
            label, color, bg, border = "Impacto alto", "#dc2626", "#fef2f2", "#fca5a5"
        eff_sign = "+" if effect >= 0 else "−"
        tau_str = f"{stat_label} = {eff_sign}{abs_effect:.2f}"
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


# ── Commercial calendar ──────────────────────────────────────────────────────

# (label, cell_bg, cell_fg, cell_border)
_COMMERCIAL_EVENTS: dict[str, dict] = {
    "rebajas_invierno": {
        "label": "Rebajas de invierno",
        "short": "Reb.I",
        "icon": "fas fa-tag",
        "color": "#1d4ed8",
        "cell": ("#dbeafe", "#1d4ed8", "#bfdbfe"),
        "desc": "Temporada de descuentos post-Navidad (enero–febrero). Alto potencial de tráfico en moda y complementos.",
        "cfg_key": "rebajas_invierno",
        "paises": ["ES"],
    },
    "rebajas_verano": {
        "label": "Rebajas de verano",
        "short": "Reb.V",
        "icon": "fas fa-sun",
        "color": "#b45309",
        "cell": ("#fef3c7", "#b45309", "#fde68a"),
        "desc": "Temporada de rebajas estival (julio–septiembre). Impacto moderado en fashion; menor en otros segmentos.",
        "cfg_key": "rebajas_verano",
        "paises": ["ES"],
    },
    "black_friday": {
        "label": "Black Friday",
        "short": "BF",
        "icon": "fas fa-bolt",
        "color": "#f9fafb",
        "cell": ("#1f2937", "#f9fafb", "#111827"),
        "desc": "Semana de descuentos masivos (último viernes de noviembre y días previos). Pico de tráfico concentrado.",
        "cfg_key": "black_friday",
        "paises": ["ES", "MX"],
    },
    "cyber_monday": {
        "label": "Cyber Monday",
        "short": "CM",
        "icon": "fas fa-laptop",
        "color": "#3730a3",
        "cell": ("#eef2ff", "#3730a3", "#c7d2fe"),
        "desc": "Lunes de ofertas digitales tras el Black Friday. Impacto más online que físico.",
        "cfg_key": "cyber_monday",
        "paises": ["ES", "MX"],
    },
    "navidad_compras": {
        "label": "Campaña de Navidad",
        "short": "Navid",
        "icon": "fas fa-gift",
        "color": "#9d174d",
        "cell": ("#fce7f3", "#9d174d", "#fbcfe8"),
        "desc": "Compras navideñas (1–24 dic). Máximo pico anual de tráfico en retail.",
        "cfg_key": "navidad_compras",
        "paises": ["ES", "MX"],
    },
    "reyes_compras": {
        "label": "Campaña de Reyes",
        "short": "Reyes",
        "icon": "fas fa-star",
        "color": "#6d28d9",
        "cell": ("#f5f3ff", "#6d28d9", "#ddd6fe"),
        "desc": "Compras para Reyes Magos (2–5 enero). Segundo gran pico de tráfico en diciembre–enero.",
        "cfg_key": "reyes_compras",
        "paises": ["ES"],
    },
    "san_valentin": {
        "label": "San Valentín",
        "short": "S.Val",
        "icon": "fas fa-heart",
        "color": "#be185d",
        "cell": ("#fdf2f8", "#be185d", "#fbcfe8"),
        "desc": "Semana del 14 de febrero. Impacto notable en complementos, cosmética y regalos.",
        "cfg_key": "san_valentin",
        "paises": ["ES", "MX"],
    },
    "dia_madre": {
        "label": "Día de la Madre (ES)",
        "short": "D.Mad",
        "icon": "fas fa-heart",
        "color": "#a21caf",
        "cell": ("#fdf4ff", "#a21caf", "#f0abfc"),
        "desc": "Primer domingo de mayo y semana previa. Impacto en moda, cosmética y hogar.",
        "cfg_key": "dia_madre",
        "paises": ["ES"],
    },
    "buen_fin_mx": {
        "label": "Buen Fin",
        "short": "BFin",
        "icon": "fas fa-bolt",
        "color": "#f9fafb",
        "cell": ("#1f2937", "#f9fafb", "#111827"),
        "desc": "Tercer viernes de noviembre (4 días). Equivalente mexicano al Black Friday.",
        "cfg_key": "buen_fin_mx",
        "paises": ["MX"],
    },
    "dia_muertos": {
        "label": "Día de Muertos",
        "short": "D.Mu",
        "icon": "fas fa-skull",
        "color": "#6d28d9",
        "cell": ("#f5f3ff", "#6d28d9", "#ddd6fe"),
        "desc": "31 oct – 2 nov. Impulso en decoración, disfraces y temporada Halloween.",
        "cfg_key": "dia_muertos",
        "paises": ["MX"],
    },
    "dia_madre_mx": {
        "label": "Día de la Madre (MX)",
        "short": "D.MaMX",
        "icon": "fas fa-heart",
        "color": "#be185d",
        "cell": ("#fdf2f8", "#be185d", "#fbcfe8"),
        "desc": "10 de mayo (fecha fija). Impacto intenso y concentrado en moda y regalos.",
        "cfg_key": "dia_madre_mx",
        "paises": ["MX"],
    },
    "regreso_clases_mx": {
        "label": "Regreso a clases",
        "short": "R.Cl",
        "icon": "fas fa-school",
        "color": "#15803d",
        "cell": ("#f0fdf4", "#15803d", "#bbf7d0"),
        "desc": "Agosto: compras de útiles y ropa escolar. Impacto fuerte en formatos de bazar y moda.",
        "cfg_key": "regreso_clases_mx",
        "paises": ["MX"],
    },
}

_TIPO_CELL: dict[str, tuple[str, str, str]] = {
    "promocion": ("#fff7ed", "#c2410c", "#fed7aa"),
    "oferta": ("#f0f9ff", "#0369a1", "#bae6fd"),
    "lanzamiento": ("#f0fdf4", "#15803d", "#bbf7d0"),
    "otro": ("#f9fafb", "#4b5563", "#e5e7eb"),
}


def _event_date_ranges(year: int, event_key: str) -> list[tuple[date, date]]:
    """Returns (start, end) windows when the event is active for the given calendar year."""

    def _last_weekday_of_month(y: int, month: int, weekday: int) -> date:
        import calendar as _cal

        last = date(y, month, _cal.monthrange(y, month)[1])
        while last.weekday() != weekday:
            last -= timedelta(days=1)
        return last

    def _nth_weekday_of_month(y: int, month: int, weekday: int, n: int) -> date:
        d = date(y, month, 1)
        count = 0
        while True:
            if d.weekday() == weekday:
                count += 1
                if count == n:
                    return d
            d += timedelta(days=1)

    if event_key == "rebajas_invierno":
        return [(date(year, 1, 2), date(year, 2, 15))]
    if event_key == "rebajas_verano":
        return [(date(year, 7, 1), date(year, 9, 15))]
    if event_key == "black_friday":
        bf = _last_weekday_of_month(year, 11, 4)  # last Friday
        return [(bf - timedelta(days=3), bf + timedelta(days=1))]  # Mon–Sat
    if event_key == "cyber_monday":
        bf = _last_weekday_of_month(year, 11, 4)
        cm = bf + timedelta(days=3)  # Monday after BF
        return [(cm, cm + timedelta(days=1))]
    if event_key == "navidad_compras":
        return [(date(year, 12, 1), date(year, 12, 24))]
    if event_key == "reyes_compras":
        return [(date(year, 1, 2), date(year, 1, 5))]
    if event_key == "san_valentin":
        return [(date(year, 2, 7), date(year, 2, 14))]
    if event_key == "dia_madre":
        first_sun = _nth_weekday_of_month(year, 5, 6, 1)
        return [(first_sun - timedelta(days=6), first_sun)]
    if event_key == "buen_fin_mx":
        third_fri = _nth_weekday_of_month(year, 11, 4, 3)
        return [(third_fri, third_fri + timedelta(days=3))]
    if event_key == "dia_muertos":
        return [(date(year, 10, 31), date(year, 11, 2))]
    if event_key == "dia_madre_mx":
        return [(date(year, 5, 9), date(year, 5, 11))]
    if event_key == "regreso_clases_mx":
        return [(date(year, 8, 15), date(year, 8, 31))]
    return []


def _build_event_flag_series(fmin: date, fmax: date, event_key: str) -> pd.Series:
    """Daily 0/1 Series indexed by Timestamp across [fmin, fmax]."""
    active: set[date] = set()
    for year in range(fmin.year - 1, fmax.year + 2):
        for start, end in _event_date_ranges(year, event_key):
            d = max(start, fmin)
            while d <= min(end, fmax):
                active.add(d)
                d += timedelta(days=1)
    idx = pd.date_range(fmin, fmax, freq="D")
    return pd.Series([1.0 if d.date() in active else 0.0 for d in idx], index=idx)


def _fmt_date_es(d: date) -> str:
    months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{d.day} {months[d.month - 1]}"


_GROUP_META = [
    ("alto", "▲ Impacto alto", "#b91c1c", "#fff1f2"),
    ("moderado", "▲ Impacto moderado", "#92400e", "#fffbeb"),
    ("leve", "Impacto leve", "#6b7280", "#f9fafb"),
    ("tendencia", "Tendencia (muestra pequeña)", "#1d4ed8", "#eff6ff"),
    ("sin_impacto", "Sin impacto detectado", "#9ca3af", "#f9fafb"),
    ("sin_datos", "Sin datos históricos", "#d1d5db", "#f9fafb"),
]


def _compute_event_stats(g0, g1) -> tuple[str, str, str]:
    """Returns (group_key, stat_txt, stat_color) for a Mann-Whitney comparison.

    For events with < 10 event days, uses uplift % instead of a non-significant
    test result — avoids "Sin impacto" when only 1-2 occurrences exist in history.
    """
    import numpy as np

    n0, n1 = len(g0), len(g1)

    uplift_str = ""
    if n1 > 0 and n0 > 0:
        base_mean = float(np.mean(g0))
        if base_mean > 0:
            uplift = (float(np.mean(g1)) - base_mean) / base_mean * 100
            s = "+" if uplift >= 0 else ""
            uplift_str = f"{s}{uplift:.0f}% vs base"

    if n0 < 5 or n1 < 5:
        note = f" · {uplift_str}" if uplift_str else ""
        return "sin_datos", f"n={n1} días{note}", "#9ca3af"

    effect, p = _mann_whitney_np(g0, g1)
    abs_e = abs(effect)
    sign = "↑" if effect >= 0 else "↓"
    r_str = f"r={sign}{abs_e:.2f}"
    p_str = (
        "p<0,001" if p < 0.001 else "p<0,01" if p < 0.01 else "p<0,05" if p < 0.05 else f"p={p:.2f}"
    )

    if p > 0.1 or abs_e < 0.1:
        if n1 < 10 and uplift_str:
            return "tendencia", f"n={n1} días · {uplift_str}", "#1d4ed8"
        return "sin_impacto", "Sin impacto detectado", "#9ca3af"
    elif abs_e >= 0.45:
        note = f" · {uplift_str}" if uplift_str else ""
        return "alto", f"{r_str} · {p_str}{note}", "#b91c1c"
    elif abs_e >= 0.25:
        note = f" · {uplift_str}" if uplift_str else ""
        return "moderado", f"{r_str} · {p_str}{note}", "#92400e"
    else:
        return "leve", f"{r_str} · {p_str}", "#6b7280"


def _calendar_comercial_section(
    df: pd.DataFrame,
    fmin_p: date,
    fecha_max: date,
    location_uuid: str | None,
    festivos: dict[date, str] | None = None,
) -> html.Div | None:
    """Calendar grid + legend for commercial events and own events."""
    if df is None or df.empty:
        return None
    if "fecha_dt" not in df.columns or "unique_visitors" not in df.columns:
        return None

    try:
        from src.db.queries import get_org_info

        org = get_org_info(location_uuid) if location_uuid else {}
        config_cal: dict = org.get("config_calendario", {})
        pais: str = (org.get("pais_codigo") or "ES").upper()
    except Exception:
        config_cal = {}
        pais = "ES"

    v_daily = df.groupby("fecha_dt")["unique_visitors"].sum().sort_index()
    if v_daily.empty or len(v_daily) < 20:
        return None

    fmin_df = min(v_daily.index)
    fmax_df = max(v_daily.index)

    # Build event_days dict: {date: (short_label, bg, fg, border)}
    # Lower-priority sources first (supercalendario), own events overwrite last
    event_days: dict[date, tuple[str, str, str, str]] = {}
    # events_by_group: {grp_key: [{"cell": (bg,fg,border), "label": str, "stat": str,
    #                                "stat_color": str, "icon": str|None}]}
    events_by_group: dict[str, list[dict]] = {k: [] for k, *_ in _GROUP_META}

    # ── Supercalendario ───────────────────────────────────────────────────────
    for event_key, meta in _COMMERCIAL_EVENTS.items():
        if pais not in meta["paises"]:
            continue
        if not config_cal.get(meta["cfg_key"], True):
            continue

        cell_bg, cell_fg, cell_border = meta["cell"]
        short = meta["short"]

        # Paint days in the analysis period
        for year in range(fmin_p.year - 1, fecha_max.year + 2):
            for start, end in _event_date_ranges(year, event_key):
                d = max(start, fmin_p)
                while d <= min(end, fecha_max):
                    event_days[d] = (short, cell_bg, cell_fg, f"1px solid {cell_border}")
                    d += timedelta(days=1)

        # Compute impact using full history
        flag_s = _build_event_flag_series(fmin_df, fmax_df, event_key)
        flag_s.index = pd.to_datetime(flag_s.index)
        v_ts = v_daily.copy()
        v_ts.index = pd.to_datetime(v_ts.index)
        merged = pd.DataFrame({"flag": flag_s, "v": v_ts}).dropna()
        g0 = merged.loc[merged["flag"] == 0, "v"].to_numpy()
        g1 = merged.loc[merged["flag"] == 1, "v"].to_numpy()
        grp, stat_txt, stat_color = _compute_event_stats(g0, g1)

        events_by_group[grp].append(
            {
                "cell": (cell_bg, cell_fg, cell_border),
                "label": meta["label"],
                "stat": stat_txt,
                "stat_color": stat_color,
                "icon": None,
            }
        )

    # ── Eventos propios ───────────────────────────────────────────────────────
    ep_rows: list = []
    if location_uuid:
        try:
            from src.db.store import get_conn

            ep_rows = (
                get_conn()
                .execute(
                    "SELECT id, nombre, tipo, descripcion, fecha_inicio, fecha_fin "
                    "FROM eventos_propios "
                    "WHERE ubicacion_id = ? AND activo = TRUE "
                    "ORDER BY fecha_inicio",
                    [location_uuid],
                )
                .fetchall()
            )
        except Exception:
            ep_rows = []

    _TIPO_ICON = {
        "promocion": "fas fa-percent",
        "oferta": "fas fa-tags",
        "lanzamiento": "fas fa-rocket",
        "otro": "fas fa-calendar-plus",
    }

    for _ep_id, ep_nombre, ep_tipo, _ep_desc, ep_fi, ep_ff in ep_rows:
        ep_fi = ep_fi if isinstance(ep_fi, date) else date.fromisoformat(str(ep_fi))
        ep_ff = ep_ff if isinstance(ep_ff, date) else date.fromisoformat(str(ep_ff))
        cell_bg, cell_fg, cell_border = _TIPO_CELL.get(ep_tipo or "otro", _TIPO_CELL["otro"])
        short_ep = ep_nombre[:6]

        # Paint days (own events overwrite supercalendario)
        d = max(ep_fi, fmin_p)
        while d <= min(ep_ff, fecha_max):
            event_days[d] = (short_ep, cell_bg, cell_fg, f"1px solid {cell_border}")
            d += timedelta(days=1)

        # Compute impact using full history
        idx_ts = pd.to_datetime(pd.date_range(fmin_df, fmax_df, freq="D"))
        flag_ep = pd.Series(
            [1.0 if ep_fi <= d2.date() <= ep_ff else 0.0 for d2 in idx_ts], index=idx_ts
        )
        v_ts2 = v_daily.copy()
        v_ts2.index = pd.to_datetime(v_ts2.index)
        merged2 = pd.DataFrame({"flag": flag_ep, "v": v_ts2}).dropna()
        g0_ep = merged2.loc[merged2["flag"] == 0, "v"].to_numpy()
        g1_ep = merged2.loc[merged2["flag"] == 1, "v"].to_numpy()
        grp_ep, stat_txt_ep, stat_color_ep = _compute_event_stats(g0_ep, g1_ep)

        ep_icon = _TIPO_ICON.get(ep_tipo or "otro", _TIPO_ICON["otro"])
        tipo_label = (ep_tipo or "otro").capitalize()

        events_by_group[grp_ep].append(
            {
                "cell": (cell_bg, cell_fg, cell_border),
                "label": ep_nombre,
                "stat": stat_txt_ep,
                "stat_color": stat_color_ep,
                "icon": ep_icon,
                "sublabel": tipo_label,
            }
        )

    if not event_days and not ep_rows:
        return None

    # ── Compact accordion grouped by impact ───────────────────────────────────
    first_active: str | None = None
    accordion_items = []
    for grp_key, grp_label, grp_color, grp_bg in _GROUP_META:
        entries = events_by_group.get(grp_key, [])
        if not entries:
            continue
        if first_active is None:
            first_active = grp_key

        event_rows = []
        for e in entries:
            bg, fg, border = e["cell"]
            swatch = html.Span(
                "■",
                style={
                    "color": fg,
                    "backgroundColor": bg,
                    "border": f"1px solid {border}",
                    "borderRadius": "3px",
                    "padding": "0 3px",
                    "marginRight": "6px",
                    "fontSize": "0.78rem",
                    "display": "inline-block",
                },
            )
            icon_el = (
                html.I(className=f"{e['icon']} me-1", style={"color": fg, "fontSize": "0.68rem"})
                if e.get("icon")
                else None
            )
            sublabel_el = (
                html.Span(
                    f"· {e['sublabel']}",
                    style={"fontSize": "0.68rem", "color": fg, "marginLeft": "3px"},
                )
                if e.get("sublabel")
                else None
            )
            event_rows.append(
                html.Div(
                    [
                        c
                        for c in [
                            swatch,
                            icon_el,
                            html.Span(
                                e["label"],
                                style={
                                    "fontSize": "0.75rem",
                                    "color": "#374151",
                                    "fontWeight": "500",
                                },
                            ),
                            sublabel_el,
                            html.Span(
                                e["stat"],
                                style={
                                    "fontSize": "0.70rem",
                                    "color": e["stat_color"],
                                    "marginLeft": "6px",
                                },
                            ),
                        ]
                        if c is not None
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "padding": "3px 0",
                        "borderBottom": "1px solid #f3f4f6",
                    },
                )
            )

        title_el = html.Span(
            [
                html.Span("●  ", style={"color": grp_color, "fontSize": "0.85rem"}),
                html.Span(
                    grp_label,
                    style={"fontSize": "0.76rem", "fontWeight": "600", "color": grp_color},
                ),
                dbc.Badge(
                    str(len(entries)),
                    pill=True,
                    color="light",
                    style={
                        "color": grp_color,
                        "border": f"1px solid {grp_color}",
                        "fontSize": "0.65rem",
                        "marginLeft": "7px",
                    },
                ),
            ],
            style={"display": "inline-flex", "alignItems": "center"},
        )

        accordion_items.append(
            dbc.AccordionItem(
                html.Div(event_rows, style={"paddingTop": "2px"}),
                title=title_el,
                item_id=grp_key,
                style={
                    "borderLeft": f"3px solid {grp_color}",
                    "marginBottom": "2px",
                    "borderRadius": "0 4px 4px 0",
                },
            )
        )

    impact_accordion = (
        dbc.Accordion(
            accordion_items,
            active_item=first_active,
            flush=True,
            className="mt-2",
            style={"fontSize": "0.78rem"},
        )
        if accordion_items
        else None
    )

    # ── Calendar legend header ────────────────────────────────────────────────
    cal_legend = html.Div(
        [
            html.Span("■ Festivo  ", style={"color": "#856404", "fontSize": "0.72rem"}),
            html.Span("■ Sábado  ", style={"color": "#6c757d", "fontSize": "0.72rem"}),
            html.Span("■ Domingo  ", style={"color": "#adb5bd", "fontSize": "0.72rem"}),
            html.Span("■ Laborable", style={"color": "#495057", "fontSize": "0.72rem"}),
        ],
        className="mb-1",
    )

    return html.Div(
        [
            _sub_header("fas fa-calendar-alt", "Calendario comercial", "#8E44AD"),
            cal_legend,
            _build_calendar(fmin_p, fecha_max, festivos or {}, event_days=event_days),
            impact_accordion,
        ],
        className="mt-3",
    )


# ── Sentence composition ─────────────────────────────────────────────────────


def _periodo_labels(ventana: str) -> tuple[str, str, str]:
    """(per_act_lower, lbl_sa, lbl_msa) — lowercase, ready for composition."""
    if ventana == "mes":
        return (
            "en los últimos 28 días",
            "los 28 días previos",
            "el mismo período del año pasado",
        )
    return "en los últimos 7 días", "los 7 días previos", "la misma semana del año pasado"


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
        _t(" días comerciales posibles"),
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

    elif señal_id == "eoh_viajeros_total":
        inicio = [
            _t("Los hoteles de Madrid registraron "),
            _bold(_fmt_val(val_act, "", "monthly_value")),
            _t(f" viajeros {per}"),
        ]

    elif señal_id == "eoh_pernoctaciones_total":
        inicio = [
            _t("Se registraron "),
            _bold(_fmt_val(val_act, "", "monthly_value")),
            _t(f" pernoctaciones hoteleras {per}"),
        ]

    elif señal_id == "egatur_gasto_medio_diario":
        inicio = [
            _t("El gasto medio diario del turista internacional fue de "),
            _bold(_fmt_val(val_act, suffix, method)),
            _t(f" {per}"),
        ]

    elif señal_id == "egatur_duracion_media_viaje":
        inicio = [
            _t("La duración media del viaje del turista internacional fue de "),
            _bold(_fmt_val(val_act, suffix, method)),
            _t(f" {per}"),
        ]

    else:
        label = _SIGNAL_REGISTRY.get(
            señal_id, (señal_id.replace("_", " ").title(), suffix, method)
        )[0]
        inicio = [_t(f"{label}: "), _bold(_fmt_val(val_act, suffix, method)), _t(f" {per}")]

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


def _build_calendar(
    fmin: date,
    fmax: date,
    festivos: dict[date, str],
    eventos: dict[date, int] | None = None,
    event_days: dict[date, tuple[str, str, str, str]] | None = None,
    dias_ok: set[date] | None = None,
    dias_imp: set[date] | None = None,
) -> html.Div:
    # event_days: {date: (short_label, bg, fg, border)}
    # dias_ok: dates with real (non-imputed) data — when provided, past days not in
    #          dias_ok|dias_imp are shown as missing
    # dias_imp: dates whose data was mean-imputed (imputado=TRUE)
    hoy = date.today()
    completeness_mode = dias_ok is not None
    _dias_imp = dias_imp or set()

    start = fmin - timedelta(days=fmin.weekday())
    end_d = fmax + timedelta(days=(6 - fmax.weekday()))

    header = html.Tr(
        [
            html.Th(
                d,
                style={
                    "fontSize": "0.76rem",
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
            ev_style = (event_days or {}).get(d)  # (short_label, bg, fg, border)

            is_past = d < hoy
            is_missing = completeness_mode and in_period and is_past and d not in dias_ok and d not in _dias_imp  # type: ignore[operator]
            is_imputado = in_period and d in _dias_imp

            if not in_period:
                bg, color, fw, border = "transparent", "#dee2e6", "normal", "none"
            elif is_missing:
                bg, color, fw, border = "#fee2e2", "#b91c1c", "normal", "1px solid #fca5a5"
            elif is_imputado:
                bg, color, fw, border = "#fffbeb", "#92400e", "normal", "1px solid #fcd34d"
            elif is_festivo:
                bg, color, fw, border = "#fff3cd", "#856404", "700", "1px solid #ffc107"
            elif ev_style:
                _, bg, color, border = ev_style
                fw = "normal"
            elif is_sunday:
                bg, color, fw, border = "#f8f9fa", "#adb5bd", "normal", "1px solid #e9ecef"
            elif is_saturday:
                bg, color, fw, border = "#f0f4fb", "#6c757d", "normal", "1px solid #e9ecef"
            else:
                bg, color, fw, border = "#ffffff", "#212529", "normal", "1px solid #e9ecef"

            festivo_name = festivos.get(d, "")
            n_eventos = eventos.get(d, 0) if eventos else 0
            children: list = [
                html.Span(
                    str(d.day), style={"display": "block", "fontWeight": fw, "fontSize": "0.9rem"}
                )
            ]
            if is_missing and in_period:
                children.append(
                    html.Span(
                        "×",
                        title="Sin datos",
                        style={
                            "fontSize": "0.55rem",
                            "display": "block",
                            "lineHeight": "1",
                            "color": "#b91c1c",
                        },
                    )
                )
            elif is_imputado and in_period:
                children.append(
                    html.Span(
                        "≈",
                        title="Estimado por media",
                        style={
                            "fontSize": "0.6rem",
                            "display": "block",
                            "lineHeight": "1",
                            "color": "#92400e",
                        },
                    )
                )
            elif festivo_name and in_period:
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
            elif ev_style and in_period:
                ev_label = ev_style[0]
                if ev_label:
                    children.append(
                        html.Span(
                            ev_label,
                            style={
                                "fontSize": "0.52rem",
                                "display": "block",
                                "lineHeight": "1.15",
                                "color": color,
                                "wordBreak": "break-word",
                            },
                        )
                    )
            if n_eventos > 0 and in_period:
                children.append(
                    html.Span(
                        "●",
                        title=f"{n_eventos} eventos",
                        style={
                            "fontSize": "0.5rem",
                            "display": "block",
                            "color": "#0052CC",
                            "lineHeight": "1",
                        },
                    )
                )

            cells.append(
                html.Td(
                    children,
                    style={
                        "textAlign": "center",
                        "padding": "6px 3px",
                        "backgroundColor": bg,
                        "color": color,
                        "borderRadius": "5px",
                        "minWidth": "42px",
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
                "borderSpacing": "4px",
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


def _kpi_stat(label: str, value: str, delta: float | None = None) -> html.Div:
    """Compact inline stat chip for the blue callout KPI row."""
    children = [
        html.Span(label, style={"fontSize": "0.68rem", "color": "#64748b", "display": "block"}),
        html.Span(value, style={"fontSize": "1.05rem", "fontWeight": "700", "color": "#1e293b"}),
    ]
    if delta is not None:
        col = _C_POS if delta > 0 else _C_NEG if delta < 0 else _C_NEU
        arrow = "▲" if delta > 0 else "▼" if delta < 0 else "="
        children.append(
            html.Span(
                f" {arrow} {delta:+.1f}%",
                style={"fontSize": "0.72rem", "fontWeight": "600", "color": col},
            )
        )
    return html.Div(children, style={"paddingRight": "20px"})


def _narrative_block(by_enum: dict[int, dict], ventana: str) -> html.Div:
    """Blue callout box with KPI row + 2-3 interpretive sentences at the top of Resumen."""
    _, lbl_sa, _ = _periodo_labels(ventana)

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
            ext_s = f"{ext['d_sa']:+.1f}%"
            int_s = f"{int_['d_sa']:+.1f}%"
            if ext["d_sa"] > 5 and gap > 5:
                if gap > 15:
                    parts.append(
                        f"Buen crecimiento de tráfico exterior ({ext_s}) pero la tienda no"
                        f" sigue el mismo ritmo ({int_s}). Revisa los elementos de conversión"
                        " de calle a tienda."
                    )
                else:
                    parts.append(
                        f"El exterior gana tráfico ({ext_s}) pero la captación en tienda"
                        f" crece menos ({int_s}). Hay margen de mejora en la conversión."
                    )
            elif ext["d_sa"] > 0 and int_["d_sa"] < -5:
                parts.append(
                    f"Más tráfico exterior ({ext_s}) pero caída en tienda ({int_s})."
                    " El local no está convirtiendo el paso de calle."
                )
            elif n_pos == len(deltas):
                parts.append(
                    f"Crecimiento generalizado respecto a {lbl_sa}"
                    f": exterior {ext_s}, tienda {int_s}."
                )
            elif n_neg == len(deltas):
                parts.append(
                    f"Caída generalizada respecto a {lbl_sa}" f": exterior {ext_s}, tienda {int_s}."
                )
            elif n_pos > n_neg:
                parts.append(
                    f"Mayoría de zonas con crecimiento respecto a {lbl_sa}"
                    f" (exterior {ext_s}, tienda {int_s})."
                )
            else:
                parts.append(
                    f"Tendencia mixta: exterior {ext_s}, tienda {int_s} respecto a {lbl_sa}."
                )
        elif n_pos == len(deltas):
            parts.append(f"Crecimiento en todas las zonas respecto a {lbl_sa}.")
        elif n_neg == len(deltas):
            parts.append(f"Caída generalizada respecto a {lbl_sa}.")
        else:
            parts.append("Tendencia mixta según zona.")

        # Checkout alert
        caja = by_enum.get(0)
        if caja and caja["d_sa"] is not None and caja["d_sa"] < -20:
            parts.append(
                f"La zona de caja registra una caída pronunciada ({caja['d_sa']:+.1f}%)."
                " Revisar disponibilidad y atención en caja."
            )

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

    # ── KPI row ───────────────────────────────────────────────────────────────
    kpi_items = []

    # Total visitas: exterior si existe, sino suma de todas las zonas
    ref_zone = ext or (next(iter(by_enum.values()), None) if by_enum else None)
    if ref_zone:
        vis_total = ref_zone["vis_act"]
        delta_vis = ref_zone.get("d_sa")
        zone_lbl = "Visitas ext." if ext else "Visitas"
        kpi_items.append(_kpi_stat(zone_lbl, f"{vis_total:,.0f}".replace(",", "."), delta_vis))

    # Visitas tienda (si hay exterior separado)
    if ext and int_ and int_["vis_act"] > 0:
        kpi_items.append(
            _kpi_stat(
                "Visitas tienda", f"{int_['vis_act']:,.0f}".replace(",", "."), int_.get("d_sa")
            )
        )

    # Estancia media
    dwell_grp = int_ or ref_zone
    if dwell_grp and dwell_grp.get("est_mean", 0) > 0:
        est = dwell_grp["est_mean"]
        est_sa = dwell_grp.get("est_sa_mean", 0)
        delta_est = ((est - est_sa) / est_sa * 100) if est_sa > 0 else None
        kpi_items.append(_kpi_stat("Estancia media", f"{est:.1f} min", delta_est))

    # Ratio conversión exterior → tienda
    if ext and int_ and ext["vis_act"] > 0 and int_["vis_act"] > 0:
        ratio = int_["vis_act"] / ext["vis_act"] * 100
        ratio_sa = (int_["vis_sa"] / ext["vis_sa"] * 100) if ext.get("vis_sa", 0) > 0 else None
        delta_ratio = (ratio - ratio_sa) if ratio_sa is not None else None
        kpi_items.append(_kpi_stat("Conversión", f"{ratio:.0f}%", delta_ratio))

    kpi_row = html.Div(
        kpi_items,
        style={
            "display": "flex",
            "flexWrap": "wrap",
            "marginBottom": "10px",
            "paddingBottom": "10px",
            "borderBottom": "1px solid rgba(0,82,204,0.15)",
        },
    )

    return html.Div(
        [
            kpi_row,
            html.P(
                " ".join(parts),
                style={
                    "fontSize": _SZ_PROSE,
                    "marginBottom": "0",
                    "lineHeight": "1.7",
                    "color": "#1e293b",
                },
            ),
        ],
        style={
            "backgroundColor": "#f0f4fb",
            "borderLeft": "3px solid #0052CC",
            "borderRadius": "0 6px 6px 0",
            "padding": "12px 16px",
            "marginBottom": "16px",
        },
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

    _next_enum = {2: 1, 1: 0}
    _zone_name = {
        ze: grp["zona_names"][0] if grp["zona_names"] else str(ze) for ze, grp in by_enum.items()
    }

    blocks = []
    for ze in sorted(by_enum.keys(), reverse=True):  # higher enum first (exterior before interior)
        grp = by_enum[ze]
        vis = grp["vis_act"]
        vis_sa = grp["vis_sama"] if grp["vis_sama"] > 0 else None
        vis_msa = grp["vis_msaa"] if grp["vis_msaa"] > 0 else None
        blocks.append(_zone_header(ze))
        blocks.append(_sentence_visitantes(ze, vis, vis_sa, vis_msa, ventana))
        nxt = _next_enum.get(ze)
        if nxt is not None and nxt in by_enum and vis > 0:
            nxt_vis = by_enum[nxt]["vis_act"]
            nxt_vis_sa = by_enum[nxt]["vis_sama"]
            ratio = nxt_vis / vis * 100
            ratio_sa = (
                (nxt_vis_sa / grp["vis_sama"] * 100)
                if grp["vis_sama"] > 0 and nxt_vis_sa > 0
                else None
            )
            txt = f"De los {vis:,} visitantes de {_zone_name[ze]}, el {ratio:.1f}% accedió a {_zone_name[nxt]} ({nxt_vis:,}).".replace(
                ",", "."
            )
            if ratio_sa is not None:
                diff = ratio - ratio_sa
                if abs(diff) >= 0.5:
                    sign = "+" if diff >= 0 else ""
                    txt += f" {sign}{diff:.1f}pp respecto al período previo."
            blocks.append(
                html.P(
                    txt,
                    className="text-muted mb-2 mt-1",
                    style={"fontSize": "0.82rem", "fontStyle": "italic"},
                )
            )
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
    return html.Div([narrative] + vis_blocks)


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
    ciudad: str = "",
) -> html.Div:
    # ── Tráfico exterior ──────────────────────────────────────────────────────
    traffic = (
        _visitor_blocks(zonas_data, {2}, df, fmin_msaa, fmax_msaa, ventana) if zonas_data else []
    )

    # ── Señales externas ──────────────────────────────────────────────────────
    sentences = []

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

            signal_ids = _get_context_signals(location_uuid, include_active=True)
            for señal_id in signal_ids:
                if señal_id not in available or señal_id not in _SIGNAL_REGISTRY:
                    continue
                _label, suffix, method = _SIGNAL_REGISTRY[señal_id]
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

    señales_header = (
        [_sub_header("fas fa-cloud-sun", "Datos externos", "#E67E22")]
        if sentences and traffic
        else []
    )

    return html.Div(traffic + señales_header + [html.Div(sentences)])


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
    location_uuid: str | None = None,
) -> html.Div:
    dias_v = 28 if ventana == "mes" else 7

    ap_act = _dias_apertura(fmin_p, fecha_max, festivos)
    ap_sa = _dias_apertura(fmin_sama, fmax_sama, festivos)
    ap_msa = _dias_apertura(fmin_msaa, fmax_msaa, festivos)

    # ── Tráfico interior: tienda (1) y caja (0) por separado ─────────────────
    traffic = (
        _visitor_blocks(zonas_data, {0, 1}, df, fmin_msaa, fmax_msaa, ventana) if zonas_data else []
    )

    return html.Div(traffic + [_sentence_dias_apertura(ap_act, dias_v, ap_sa, ap_msa, ventana)])


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
                        ciudad=ciudad,
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
                        location_uuid=location_uuid,
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


def render_periodo_calendar(
    location_uuid: str | None,
    fmin_p,
    fecha_max,
) -> dbc.Card:
    """Standalone calendar card — placed above the map in the right column."""
    fmin_p = _to_date(fmin_p)
    fecha_max = _to_date(fecha_max)

    pais_codigo, ciudad = _get_location_meta(location_uuid) if location_uuid else ("ES", "")
    years = {fmin_p.year, fecha_max.year}
    festivos = _get_festivos(pais_codigo, ciudad, years)
    festivos_en_periodo = {d: n for d, n in festivos.items() if fmin_p <= d <= fecha_max}

    # Fetch event counts per day for cities that track cultural events
    eventos: dict[date, int] | None = None
    city_signals = (
        set(_get_context_signals(location_uuid, include_active=True)) if location_uuid else set()
    )
    if location_uuid and "n_eventos_culturales_dia" in city_signals:
        try:
            from src.db.queries import get_señal_diaria

            s = get_señal_diaria(
                location_uuid,
                "n_eventos_culturales_dia",
                pd.Timestamp(fmin_p),
                pd.Timestamp(fecha_max),
            )
            if s is not None and not s.empty:
                eventos = {
                    (pd.Timestamp(d).date() if not isinstance(d, date) else d): int(v)
                    for d, v in s.items()
                    if v > 0
                }
        except Exception:
            pass

    has_eventos = bool(eventos)

    # Data completeness per day
    dias_ok: set[date] = set()
    dias_imp: set[date] = set()
    if location_uuid:
        try:
            from src.db.store import get_conn as _gc

            _rows = (
                _gc()
                .execute(
                    """
                SELECT fecha, BOOL_AND(imputado) AS todo_imputado
                FROM visitas
                WHERE ubicacion_id = ? AND fecha BETWEEN ? AND ?
                GROUP BY fecha
                """,
                    [location_uuid, str(fmin_p), str(fecha_max)],
                )
                .fetchall()
            )
            for _r in _rows:
                _d = _r[0] if isinstance(_r[0], date) else _r[0].date()
                if _r[1]:
                    dias_imp.add(_d)
                else:
                    dias_ok.add(_d)
        except Exception:
            dias_ok = set()
            dias_imp = set()

    completeness_active = bool(dias_ok or dias_imp)
    legend = html.Div(
        [
            html.Span("■ Festivo  ", style={"color": "#856404", "fontSize": "0.72rem"}),
            html.Span("■ Sábado  ", style={"color": "#6c757d", "fontSize": "0.72rem"}),
            html.Span("■ Domingo  ", style={"color": "#adb5bd", "fontSize": "0.72rem"}),
            html.Span("■ Laborable", style={"color": "#495057", "fontSize": "0.72rem"}),
            *(
                [html.Span("  ● Eventos", style={"color": "#0052CC", "fontSize": "0.72rem"})]
                if has_eventos
                else []
            ),
            *(
                [
                    html.Span(
                        "  ≈ Estimado  ",
                        title="Día sin datos reales — imputado por media rolling",
                        style={"color": "#92400e", "fontSize": "0.72rem"},
                    ),
                    html.Span(
                        "× Sin datos",
                        title="Día sin datos reales ni estimación posible",
                        style={"color": "#b91c1c", "fontSize": "0.72rem"},
                    ),
                ]
                if completeness_active
                else []
            ),
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

    return dbc.Card(
        dbc.CardBody(
            [
                html.H6(
                    "Calendario del período",
                    className="fw-bold mb-2",
                    style={"fontSize": "0.88rem", "color": "#1e293b"},
                ),
                legend,
                _build_calendar(
                    fmin_p,
                    fecha_max,
                    festivos,
                    eventos=eventos,
                    dias_ok=dias_ok if completeness_active else None,
                    dias_imp=dias_imp if completeness_active else None,
                ),
                festivos_list,
            ]
        ),
        className="border-0 shadow-sm rounded-4 mb-3",
    )


def render_eventos_carousel(
    location_uuid: str | None,
    df: pd.DataFrame | None,
    fmin_p,
    fecha_max,
) -> dbc.Card | None:
    """Full-width horizontal card carousel of commercial + own events with impact stats."""
    fmin_p = _to_date(fmin_p)
    fecha_max = _to_date(fecha_max)

    if df is None or df.empty:
        return None
    if "fecha_dt" not in df.columns or "unique_visitors" not in df.columns:
        return None

    try:
        from src.db.queries import get_org_info

        org = get_org_info(location_uuid) if location_uuid else {}
        config_cal: dict = org.get("config_calendario", {})
        pais: str = (org.get("pais_codigo") or "ES").upper()
    except Exception:
        config_cal = {}
        pais = "ES"

    v_daily = df.groupby("fecha_dt")["unique_visitors"].sum().sort_index()
    if v_daily.empty or len(v_daily) < 20:
        return None

    fmin_df = min(v_daily.index)
    fmax_df = max(v_daily.index)

    events_by_group: dict[str, list[dict]] = {k: [] for k, *_ in _GROUP_META}

    for event_key, meta in _COMMERCIAL_EVENTS.items():
        if pais not in meta["paises"]:
            continue
        if not config_cal.get(meta["cfg_key"], True):
            continue

        cell_bg, cell_fg, cell_border = meta["cell"]
        flag_s = _build_event_flag_series(fmin_df, fmax_df, event_key)
        flag_s.index = pd.to_datetime(flag_s.index)
        v_ts = v_daily.copy()
        v_ts.index = pd.to_datetime(v_ts.index)
        merged = pd.DataFrame({"flag": flag_s, "v": v_ts}).dropna()
        g0 = merged.loc[merged["flag"] == 0, "v"].to_numpy()
        g1 = merged.loc[merged["flag"] == 1, "v"].to_numpy()
        grp, stat_txt, stat_color = _compute_event_stats(g0, g1)
        events_by_group[grp].append(
            {
                "cell": (cell_bg, cell_fg, cell_border),
                "label": meta["label"],
                "stat": stat_txt,
                "stat_color": stat_color,
                "icon": None,
                "sublabel": None,
            }
        )

    ep_rows: list = []
    if location_uuid:
        try:
            from src.db.store import get_conn

            ep_rows = (
                get_conn()
                .execute(
                    "SELECT id, nombre, tipo, descripcion, fecha_inicio, fecha_fin "
                    "FROM eventos_propios WHERE ubicacion_id = ? AND activo = TRUE "
                    "ORDER BY fecha_inicio",
                    [location_uuid],
                )
                .fetchall()
            )
        except Exception:
            ep_rows = []

    _TIPO_ICON = {
        "promocion": "fas fa-percent",
        "oferta": "fas fa-tags",
        "lanzamiento": "fas fa-rocket",
        "otro": "fas fa-calendar-plus",
    }

    for _ep_id, ep_nombre, ep_tipo, _ep_desc, ep_fi, ep_ff in ep_rows:
        ep_fi = ep_fi if isinstance(ep_fi, date) else date.fromisoformat(str(ep_fi))
        ep_ff = ep_ff if isinstance(ep_ff, date) else date.fromisoformat(str(ep_ff))
        cell_bg, cell_fg, cell_border = _TIPO_CELL.get(ep_tipo or "otro", _TIPO_CELL["otro"])
        idx_ts = pd.to_datetime(pd.date_range(fmin_df, fmax_df, freq="D"))
        flag_ep = pd.Series(
            [1.0 if ep_fi <= d2.date() <= ep_ff else 0.0 for d2 in idx_ts], index=idx_ts
        )
        v_ts2 = v_daily.copy()
        v_ts2.index = pd.to_datetime(v_ts2.index)
        merged2 = pd.DataFrame({"flag": flag_ep, "v": v_ts2}).dropna()
        g0_ep = merged2.loc[merged2["flag"] == 0, "v"].to_numpy()
        g1_ep = merged2.loc[merged2["flag"] == 1, "v"].to_numpy()
        grp_ep, stat_txt_ep, stat_color_ep = _compute_event_stats(g0_ep, g1_ep)
        events_by_group[grp_ep].append(
            {
                "cell": (cell_bg, cell_fg, cell_border),
                "label": ep_nombre,
                "stat": stat_txt_ep,
                "stat_color": stat_color_ep,
                "icon": _TIPO_ICON.get(ep_tipo or "otro", _TIPO_ICON["otro"]),
                "sublabel": (ep_tipo or "otro").capitalize(),
            }
        )

    cards = []
    for grp_key, grp_label, grp_color, grp_bg in _GROUP_META:
        entries = events_by_group.get(grp_key, [])
        if not entries:
            continue

        event_rows = []
        for e in entries:
            bg, fg, border = e["cell"]
            swatch = html.Span(
                "■",
                style={
                    "color": fg,
                    "backgroundColor": bg,
                    "border": f"1px solid {border}",
                    "borderRadius": "3px",
                    "padding": "0 3px",
                    "marginRight": "6px",
                    "fontSize": "0.78rem",
                    "display": "inline-block",
                    "flexShrink": "0",
                },
            )
            icon_el = (
                html.I(
                    className=f"{e['icon']} me-1",
                    style={"color": fg, "fontSize": "0.7rem"},
                )
                if e.get("icon")
                else None
            )
            sublabel_el = (
                html.Span(
                    f"· {e['sublabel']}",
                    style={"fontSize": "0.68rem", "color": "#9ca3af", "marginLeft": "3px"},
                )
                if e.get("sublabel")
                else None
            )
            event_rows.append(
                html.Div(
                    [
                        c
                        for c in [
                            swatch,
                            icon_el,
                            html.Span(
                                e["label"],
                                style={
                                    "fontSize": "0.77rem",
                                    "color": "#374151",
                                    "fontWeight": "500",
                                    "flex": "1",
                                    "minWidth": "0",
                                    "overflow": "hidden",
                                    "textOverflow": "ellipsis",
                                    "whiteSpace": "nowrap",
                                },
                            ),
                            sublabel_el,
                            html.Span(
                                e["stat"],
                                style={
                                    "fontSize": "0.72rem",
                                    "color": e["stat_color"],
                                    "marginLeft": "8px",
                                    "whiteSpace": "nowrap",
                                    "flexShrink": "0",
                                    "fontWeight": "600",
                                },
                            ),
                        ]
                        if c is not None
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "padding": "5px 0",
                        "borderBottom": "1px solid #f3f4f6",
                    },
                )
            )

        n = len(entries)
        cards.append(
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.Div(
                            [
                                html.Span("●  ", style={"color": grp_color, "fontSize": "0.85rem"}),
                                html.Span(
                                    grp_label,
                                    style={
                                        "fontSize": "0.76rem",
                                        "fontWeight": "700",
                                        "color": grp_color,
                                    },
                                ),
                                dbc.Badge(
                                    str(n),
                                    pill=True,
                                    color="light",
                                    style={
                                        "color": grp_color,
                                        "border": f"1px solid {grp_color}",
                                        "fontSize": "0.62rem",
                                        "marginLeft": "7px",
                                    },
                                ),
                            ],
                            style={"display": "inline-flex", "alignItems": "center"},
                        ),
                        style={
                            "backgroundColor": grp_bg,
                            "borderBottom": f"2px solid {grp_color}",
                            "padding": "7px 12px",
                        },
                    ),
                    dbc.CardBody(
                        html.Div(event_rows, style={"paddingTop": "2px"}),
                        style={"padding": "8px 12px"},
                    ),
                ],
                style={
                    "minWidth": "240px",
                    "maxWidth": "300px",
                    "flexShrink": "0",
                    "borderRadius": "8px",
                    "border": f"1px solid {grp_color}33",
                    "scrollSnapAlign": "start",
                },
            )
        )

    if not cards:
        return None

    return dbc.Card(
        dbc.CardBody(
            [
                html.H6(
                    [
                        html.I(
                            className="fas fa-calendar-alt me-2",
                            style={"color": "#8E44AD"},
                        ),
                        "Impacto de eventos comerciales",
                    ],
                    className="fw-bold mb-3",
                    style={"fontSize": "0.88rem", "color": "#1e293b"},
                ),
                html.Div(
                    cards,
                    style={
                        "display": "flex",
                        "gap": "10px",
                        "overflowX": "auto",
                        "paddingBottom": "6px",
                        "scrollSnapType": "x mandatory",
                    },
                ),
            ]
        ),
        className="border-0 shadow-sm rounded-4 mb-3",
    )
