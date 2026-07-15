"""
Narrative engine for the Health Check panel.

Extracted functions:
  - _load_narrative_meta
  - _veredictos_contexto
  - _narrativa
  - _render_narrativa
"""

from __future__ import annotations

from datetime import datetime, timedelta

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

from src.core.theme import C_DARK as _C_DARK
from src.core.theme import C_MUTED as _C_MUTED
from src.core.theme import C_PRIMARY as _C_PRIMARY

dias_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def formatear_fecha(fecha_obj):
    return f"{dias_semana_es[fecha_obj.weekday()]} {fecha_obj.strftime('%d/%m')}"


def calcular_delta(actual, anterior):
    if not anterior or pd.isna(anterior):
        return 0
    return (actual - anterior) / anterior * 100


# ── DB helpers ────────────────────────────────────────────────────────────────


def _load_narrative_meta(conn) -> tuple[dict, dict, list]:
    """
    Devuelve (cat_meta, level_meta, cat_order) desde DB.

    cat_meta:   {category_key: (icon_cls, label)}
    level_meta: {level_key:    (text_color, bg_color)}
    cat_order:  lista ordenada por sort_order
    """
    cat_meta: dict = {}
    level_meta: dict = {}
    cat_order: list = []
    try:
        for ck, lbl, icon, _ in conn.execute(
            "SELECT clave, label, icono, orden " "FROM categorias_narrativa ORDER BY orden"
        ).fetchall():
            cat_meta[ck] = (icon or "fas fa-circle", lbl or ck)
            cat_order.append(ck)
        for lk, tc, bc, _ in conn.execute(
            "SELECT clave, color_texto, color_fondo, orden " "FROM niveles_alerta ORDER BY orden"
        ).fetchall():
            level_meta[lk] = (tc, bc)
    except Exception:
        pass
    return cat_meta, level_meta, cat_order


# ── Context verdicts ──────────────────────────────────────────────────────────


def _veredictos_contexto(
    dg: float,
    fmin_act,
    fmax_act,
    fmin_ant,
    fmax_ant,
    dias_v: int,
    clima: dict,
    eventos: dict,
    location_uuid: str | None,
) -> list[tuple[str, str, str]]:
    """Returns [(nivel, icon_cls, texto), ...] — one verdict per contextual signal."""
    if abs(dg) < 2:
        return []

    if dg <= -5:
        vd = "el descenso"
    elif dg >= 5:
        vd = "el crecimiento"
    else:
        vd = "la variación observada"

    result: list[tuple[str, str, str]] = []
    prev_neg = False

    s_act = fmin_act.strftime("%Y-%m-%d")
    e_act = fmax_act.strftime("%Y-%m-%d")
    s_ant = fmin_ant.strftime("%Y-%m-%d")
    e_ant = fmax_ant.strftime("%Y-%m-%d")

    def _pl(n: int) -> str:
        return "s" if n != 1 else ""

    def _descartar(noun: str, icon: str, dato: str = "") -> None:
        nonlocal prev_neg
        if prev_neg:
            t = f"{noun} tampoco explica {vd}"
        else:
            t = f"{noun} no explica {vd}"
        t += f" ({dato})." if dato else "."
        prev_neg = True
        result.append(("secondary", icon, t))

    def _confirmar(nivel: str, icon: str, texto: str) -> None:
        nonlocal prev_neg
        prev_neg = False
        result.append((nivel, icon, texto))

    # ── Lluvia ────────────────────────────────────────────────────────────────
    if clima:
        n_act = sum(1 for k, v in clima.items() if s_act <= k <= e_act and v.get("precip", 0) > 2)
        n_ant = sum(1 for k, v in clima.items() if s_ant <= k <= e_ant and v.get("precip", 0) > 2)
        if n_act > 0 or n_ant > 0:
            if (dg < 0 and n_act - n_ant >= 2) or (dg > 0 and n_ant - n_act >= 2):
                if dg < 0:
                    _confirmar(
                        "warning",
                        "fas fa-cloud-rain",
                        f"La lluvia contribuyó al descenso: {n_act} día{_pl(n_act)} "
                        f"de precipitaciones frente a {n_ant} en el período anterior.",
                    )
                else:
                    _confirmar(
                        "secondary",
                        "fas fa-cloud-rain",
                        f"La reducción de lluvia favoreció el crecimiento "
                        f"({n_act} día{_pl(n_act)} vs. {n_ant} período anterior).",
                    )
            else:
                _descartar(
                    "La lluvia",
                    "fas fa-cloud-rain",
                    f"{n_act} día{_pl(n_act)} vs. {n_ant} anterior",
                )

        # ── Temperatura (calor + frío combinados) ─────────────────────────────
        def _avg(key, s, e):
            vals = [v.get(key) for k, v in clima.items() if s <= k <= e and v.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        tmax_act = _avg("tmax", s_act, e_act)
        tmax_ant = _avg("tmax", s_ant, e_ant)
        tmin_act = _avg("tmin", s_act, e_act)
        tmin_ant = _avg("tmin", s_ant, e_ant)

        dias_calor_act = sum(
            1 for k, v in clima.items() if s_act <= k <= e_act and (v.get("tmax") or 0) >= 30
        )
        dias_calor_ant = sum(
            1 for k, v in clima.items() if s_ant <= k <= e_ant and (v.get("tmax") or 0) >= 30
        )
        dias_frio_act = sum(
            1
            for k, v in clima.items()
            if s_act <= k <= e_act and v.get("tmax") is not None and v["tmax"] < 12
        )
        dias_frio_ant = sum(
            1
            for k, v in clima.items()
            if s_ant <= k <= e_ant and v.get("tmax") is not None and v["tmax"] < 12
        )

        if tmax_act is not None or tmax_ant is not None:
            tmx_a = tmax_act or 0
            tmx_b = tmax_ant or 0
            tmn_a = tmin_act or 0
            tmn_b = tmin_ant or 0
            icon_temp = "fas fa-temperature-half"

            calor_diff = dias_calor_act - dias_calor_ant
            frio_diff = dias_frio_act - dias_frio_ant

            resumen_temp = (
                f"temperatura media de {tmx_a:.0f}°C máx./{tmn_a:.0f}°C mín. "
                f"frente a {tmx_b:.0f}°C máx./{tmn_b:.0f}°C mín. en el período anterior"
            )

            if dg < 0 and calor_diff >= 2:
                _confirmar(
                    "warning",
                    "fas fa-sun",
                    f"El calor extremo contribuyó al descenso: {dias_calor_act} día{_pl(dias_calor_act)} "
                    f"con Tmax ≥30°C frente a {dias_calor_ant} en el período anterior "
                    f"({tmx_a:.0f}°C máx. vs. {tmx_b:.0f}°C).",
                )
            elif dg > 0 and calor_diff <= -2:
                _confirmar(
                    "secondary",
                    "fas fa-sun",
                    f"Las temperaturas más suaves favorecieron el crecimiento: "
                    f"{dias_calor_act} día{_pl(dias_calor_act)} ≥30°C frente a {dias_calor_ant} en el período anterior.",
                )
            elif dg < 0 and frio_diff >= 2:
                _confirmar(
                    "warning",
                    "fas fa-snowflake",
                    f"El frío contribuyó al descenso: {dias_frio_act} día{_pl(dias_frio_act)} "
                    f"con Tmax <12°C frente a {dias_frio_ant} en el período anterior "
                    f"({tmx_a:.0f}°C máx. vs. {tmx_b:.0f}°C).",
                )
            elif dg > 0 and frio_diff <= -2:
                _confirmar(
                    "secondary",
                    "fas fa-snowflake",
                    f"La mejoría del tiempo favoreció el crecimiento: "
                    f"{dias_frio_act} día{_pl(dias_frio_act)} <12°C frente a {dias_frio_ant} en el período anterior.",
                )
            else:
                _descartar("La temperatura", icon_temp, resumen_temp)

    # ── Eventos de alto impacto ───────────────────────────────────────────────
    if eventos:
        pasados = eventos.get("pasados_alto", [])
        ev_act = [e for e in pasados if fmin_act <= e["fecha"] <= fmax_act]
        ev_ant = [e for e in pasados if fmin_ant <= e["fecha"] <= fmax_ant]
        n_ev_act, n_ev_ant = len(ev_act), len(ev_ant)
        if n_ev_act > 0 or n_ev_ant > 0:
            if (dg > 0 and n_ev_act - n_ev_ant >= 1) or (dg < 0 and n_ev_ant - n_ev_act >= 1):
                if dg > 0:
                    titulos = "; ".join(f"«{e['titulo']}»" for e in ev_act[:2])
                    _confirmar(
                        "success",
                        "fas fa-star",
                        f"Los eventos de alto impacto impulsaron el crecimiento: {titulos}.",
                    )
                else:
                    _confirmar(
                        "warning",
                        "fas fa-star",
                        f"La menor presencia de eventos de alto impacto pesó en el descenso "
                        f"({n_ev_act} vs. {n_ev_ant} en el período anterior).",
                    )
            else:
                _descartar(
                    "Los eventos del período",
                    "fas fa-star",
                    f"{n_ev_act} evento{_pl(n_ev_act)} vs. {n_ev_ant} anterior",
                )

        # ── Cruceros del período ───────────────────────────────────────────────
        cruceros = eventos.get("cruceros", [])
        if cruceros:
            cr_act = [c for c in cruceros if fmin_act <= c["fecha"] <= fmax_act]
            cr_ant = [c for c in cruceros if fmin_ant <= c["fecha"] <= fmax_ant]
            if cr_act or cr_ant:
                n_cr_act, n_cr_ant = len(cr_act), len(cr_ant)
                pax_act = sum(c["n_pasajeros"] for c in cr_act)
                pax_ant = sum(c["n_pasajeros"] for c in cr_ant)
                if (dg > 0 and n_cr_act - n_cr_ant >= 1) or (dg < 0 and n_cr_ant - n_cr_act >= 1):
                    if dg > 0:
                        _confirmar(
                            "success",
                            "fas fa-ship",
                            f"La actividad portuaria contribuyó al crecimiento: "
                            f"{n_cr_act} escala{_pl(n_cr_act)} ({pax_act:,} pax) "
                            f"frente a {n_cr_ant} ({pax_ant:,} pax) en el período anterior.",
                        )
                    else:
                        _confirmar(
                            "warning",
                            "fas fa-ship",
                            f"La menor actividad portuaria contribuyó al descenso: "
                            f"{n_cr_act} escala{_pl(n_cr_act)} vs. {n_cr_ant} en el período anterior.",
                        )
                else:
                    _descartar(
                        "Las escalas de crucero",
                        "fas fa-ship",
                        f"{n_cr_act} escala{_pl(n_cr_act)} vs. {n_cr_ant} anterior",
                    )

    # ── Señales propias de la ubicación — agrupadas por familia ─────────────
    return result


# ── Narrative builder ─────────────────────────────────────────────────────────


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

    # ── AFLUENCIA — cifras y veredictos de contexto ──────────────────────────

    def _as_date(d):
        return d.date() if isinstance(d, datetime) else d

    _fmin_act_d = _as_date(fecha_max - timedelta(days=dias_v - 1))
    _fmax_act_d = _as_date(fecha_max)
    _fmin_ant_d = _as_date(fecha_max - timedelta(days=2 * dias_v - 1))
    _fmax_ant_d = _as_date(fecha_max - timedelta(days=dias_v))

    es_semana = ventana != "mes"
    _art = "la" if es_semana else "el"
    _adj = "analizada" if es_semana else "analizado"
    _nivel_num = (
        "danger"
        if dg <= -10
        else ("warning" if dg < -5 else ("success" if dg >= 5 else "secondary"))
    )
    _icon_num = (
        "fas fa-arrow-trend-down"
        if dg <= -5
        else ("fas fa-arrow-trend-up" if dg >= 5 else "fas fa-equals")
    )
    _add(
        "trafico",
        _nivel_num,
        _icon_num,
        f"{total_p:,} visitas en {_art} {periodo} {_adj} "
        f"frente a {total_p_a:,} en {periodo_ant} precedente ({dg:+.0f}%).",
    )
    for _nv, _ic, _tx in _veredictos_contexto(
        dg,
        _fmin_act_d,
        _fmax_act_d,
        _fmin_ant_d,
        _fmax_ant_d,
        dias_v,
        clima,
        eventos or {},
        location_uuid,
    ):
        _add("trafico", _nv, _ic, _tx)

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

    def _es_exterior(z):
        ze = z.get("zone_enum")
        if ze is not None:
            return ze == 2
        zl = z["zona"].lower()
        return "exterior" in zl or "calle" in zl

    def _es_tienda(z):
        ze = z.get("zone_enum")
        if ze is not None:
            return ze == 1
        return "tienda" in z["zona"].lower()

    for z in zonas_data:
        zn = z["zona"]
        dv = z["d"]["visitantes"]
        rv = z["r"]["visitantes"]
        av = z["a"]["visitantes"]
        zl = z["zona"].lower()

        if _es_exterior(z):
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
        elif _es_tienda(z):
            ext = next(
                (z2 for z2 in zonas_data if _es_exterior(z2)),
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

    # ── EVENTOS PRÓXIMOS ──────────────────────────────────────────────────────

    if eventos:
        proximos = eventos.get("proximos_alto", [])
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

        cruceros = eventos.get("cruceros", [])
        if cruceros:

            def _as_date_inner(d):
                return d.date() if isinstance(d, datetime) else d

            hoy_d = _as_date_inner(fecha_max)
            cr_proximos = [c for c in cruceros if c["fecha"] > hoy_d]
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


# ── Narrative renderer ────────────────────────────────────────────────────────


def _render_narrativa(items, extras=None):
    """
    Renderiza los insights del resumen como menú horizontal de tabs (uno por categoría).
    extras: dict {cat_key: html.Component} — contenido adicional (ej. gráficos) por tab.
    Solo aparecen tabs que tengan al menos un insight o extra content.

    Categorías, etiquetas, iconos y colores de nivel se cargan desde
    categorias_narrativa y niveles_alerta.
    """
    try:
        from src.db.store import get_conn

        _CAT_META, _LEVEL_COLOR, _CAT_ORDER = _load_narrative_meta(get_conn())
    except Exception:
        _CAT_META, _LEVEL_COLOR, _CAT_ORDER = {}, {}, []

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
