#!/usr/bin/env python3
"""
Simulacro dry-run de los dos orquestadores — sin escribir nada en DB.

Simula date.today() = 2026-08-01 y lanza todas las fases tal como lo harían
los timers, interceptando las escrituras en DB y reportando qué habría pasado.

Uso:
    venv/bin/python scripts/dry_run_sim.py
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

FECHA_SIM = date(2026, 8, 1)

_ANCHO = 70
_writes: list[str] = []


def _sep(titulo: str = "", char: str = "─") -> None:
    if titulo:
        pad = max(0, _ANCHO - len(titulo) - 2)
        print(f"\n{char * 2} {titulo} {char * pad}")
    else:
        print(char * _ANCHO)


# ── Wrapper DB read-only ──────────────────────────────────────────────────────


class _DryRunCursor:
    """Cursor vacío devuelto tras interceptar una escritura."""

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter([])


class _DryRunConn:
    """
    Wrappea la conexión real: pasa SELECT, intercepta INSERT/UPDATE/DELETE/etc.
    y los registra sin ejecutarlos.
    """

    _WRITE_VERBS = {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "TRUNCATE", "ALTER"}

    def __init__(self, real):
        self._real = real

    def execute(self, sql, params=None):
        verb = sql.strip().split()[0].upper() if sql.strip() else ""
        if verb in self._WRITE_VERBS:
            short = " ".join(sql.split())[:90]
            _writes.append(f"{verb}: {short}")
            return _DryRunCursor()
        return self._real.execute(sql, params)

    def executemany(self, sql, data):
        rows = list(data)
        verb = sql.strip().split()[0].upper()
        short = " ".join(sql.split())[:70]
        _writes.append(f"{verb}×{len(rows)}: {short}")

    # Pasar-through para cualquier otro método que use el código
    def __getattr__(self, name):
        return getattr(self._real, name)


# Guardamos la factory original antes de parchear
_orig_get_conn = None


def _make_dry_conn():
    return _DryRunConn(_orig_get_conn())


# ── Helpers ───────────────────────────────────────────────────────────────────


def _check_freshness_sources(periodicidad: str, max_age_h: float) -> dict[str, dict]:
    """
    Para cada fuente activa con `periodicidad`, calcula si estaría fresca
    en la fecha simulada.  Devuelve {fuente: {stale: bool, last_run: str, locs: int}}.
    """
    from src.data_ingestion._common import get_active_locations

    locs = get_active_locations()
    conn = _orig_get_conn()
    fuentes_db = conn.execute(
        "SELECT fuente FROM fuentes WHERE periodicidad = ? AND activo = TRUE",
        [periodicidad],
    ).fetchall()

    resultado = {}
    for (fuente,) in fuentes_db:
        stale_locs = []
        fresh_locs = []
        for loc in locs:
            uid = loc["ubicacion_id"]
            row = conn.execute(
                "SELECT MAX(ingerido_en) FROM valores_señales "
                "WHERE ubicacion_id = ? AND señal_id = ?",
                [uid, f"_sync_{fuente}"],
            ).fetchone()
            last = row[0] if row and row[0] else None
            if last is None:
                stale_locs.append(uid)
            else:
                age_h = (
                    FECHA_SIM.toordinal() * 24
                    - (last.date() if hasattr(last, "date") else last).toordinal() * 24
                )
                if age_h >= max_age_h:
                    stale_locs.append(uid)
                else:
                    fresh_locs.append(uid)
        resultado[fuente] = {
            "stale": len(stale_locs),
            "fresh": len(fresh_locs),
            "total": len(locs),
        }
    return resultado


# ── DIARIO ────────────────────────────────────────────────────────────────────


def sim_diario() -> None:
    _sep("SIMULACRO DIARIO — 2026-08-01 10:30 UTC", "═")

    # ── Fase 0: Árbol Aitanna ─────────────────────────────────────────────────
    _sep("Fase 0 · Árbol de ubicaciones (Aitanna API)")
    try:
        from src.data_ingestion.actualizar_arbol_ubicaciones import (
            _get_aitanna_locations,  # type: ignore[attr-defined]
        )

        raw = _get_aitanna_locations()
        print(f"  API Aitanna → {len(raw)} ubicaciones disponibles en el maestro")
    except Exception:
        # Intentamos con la función pública si la privada no existe
        try:
            import os

            import requests

            key = os.environ.get("AITANNA_API_KEY", "")
            r = requests.get(
                "https://app.aitanna.com/api/v2/locations",
                headers={"x-api-key": key},
                timeout=10,
            )
            data = r.json() if r.ok else {}
            locs = data.get("locations", data.get("data", []))
            print(f"  API Aitanna → {len(locs)} ubicaciones en el maestro")
        except Exception as e2:
            print(f"  Aitanna no alcanzable: {e2}")

    # ── Fase A: Visits (Aitanna incremental) ──────────────────────────────────
    _sep("Fase A · Visits Aitanna (incremental)")
    try:
        conn = _orig_get_conn()
        rows = conn.execute(
            "SELECT u.ubicacion_id, u.nombre, MAX(v.fecha) as ultima_visita "
            "FROM ubicaciones u LEFT JOIN visitas v USING(ubicacion_id) "
            "WHERE u.activa = TRUE "
            "GROUP BY u.ubicacion_id, u.nombre "
            "ORDER BY ultima_visita ASC NULLS FIRST"
        ).fetchall()
        print(f"  {'Ubicación':<38}  {'Último dato':>12}  {'Días pendientes':>15}")
        print(f"  {'─'*38}  {'─'*12}  {'─'*15}")
        total_dias = 0
        for uid, nombre, ultima in rows:
            if ultima is None:
                dias = "sin datos"
                total_dias += (FECHA_SIM - date(2025, 1, 1)).days
            else:
                ult = ultima if isinstance(ultima, date) else ultima.date()
                dias_n = (FECHA_SIM - ult - timedelta(days=1)).days
                dias = f"{dias_n} días" if dias_n > 0 else "al día"
                total_dias += max(0, dias_n)
            print(f"  {nombre:<38}  {str(ultima)[:10]:>12}  {dias:>15}")
        print(f"\n  Total requests Aitanna estimados: ~{total_dias} llamadas de día")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── Fase B: Ingestores diarios ────────────────────────────────────────────
    _sep("Fase B · Ingestores diarios (max_age=20h)")
    try:
        resultado = _check_freshness_sources("diaria", max_age_h=20)
        print(f"  {'Fuente':<25}  {'Stale':>6}  {'Fresh':>6}  {'Acción':>30}")
        print(f"  {'─'*25}  {'─'*6}  {'─'*6}  {'─'*30}")
        for fuente, info in sorted(resultado.items()):
            if info["stale"] > 0:
                accion = f"  ✓ procesaría {info['stale']} ubicación(es)"
            else:
                accion = "  — omitido (frescos)"
            print(f"  {fuente:<25}  {info['stale']:>6}  {info['fresh']:>6}  {accion}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Probe weather para Aug 1 (API gratuita)
    _sep("Fase B · Weather — sondeo Open-Meteo para 2026-08-01")
    try:
        import urllib.parse
        import urllib.request

        conn = _orig_get_conn()
        locs_coords = conn.execute(
            "SELECT nombre, lat, lon FROM ubicaciones WHERE activa = TRUE AND lat IS NOT NULL LIMIT 3"
        ).fetchall()
        for nombre, lat, lon in locs_coords:
            url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,precipitation_sum",
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-01",
                    "timezone": "Europe/Madrid",
                }
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                import json

                data = json.loads(resp.read())
            daily = data.get("daily", {})
            t_max = (daily.get("temperature_2m_max") or [None])[0]
            prec = (daily.get("precipitation_sum") or [None])[0]
            print(f"  {nombre[:35]:<35}  Tmax={t_max}°C  Prec={prec}mm")
    except Exception as e:
        print(f"  Open-Meteo: {e}")

    # Probe Ticketmaster para agosto en Madrid
    _sep("Fase B · Ticketmaster — eventos agosto 2026 (muestra)")
    try:
        import json
        import os
        import urllib.parse
        import urllib.request

        tm_key = os.environ.get("TICKETMASTER_API_KEY", "")
        if tm_key:
            url = "https://app.ticketmaster.com/discovery/v2/events.json?" + urllib.parse.urlencode(
                {
                    "apikey": tm_key,
                    "countryCode": "ES",
                    "startDateTime": "2026-08-01T00:00:00Z",
                    "endDateTime": "2026-08-31T23:59:59Z",
                    "size": 5,
                }
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            total = data.get("page", {}).get("totalElements", "?")
            evs = data.get("_embedded", {}).get("events", [])
            print(f"  {total} eventos en España agosto 2026 (mostrando {len(evs)}):")
            for ev in evs:
                fecha = ev.get("dates", {}).get("start", {}).get("localDate", "?")
                print(f"    [{fecha}] {ev.get('name', '?')[:55]}")
        else:
            print("  TICKETMASTER_API_KEY no configurada — omitido")
    except Exception as e:
        print(f"  Ticketmaster: {e}")

    # ── Fase C: Mensuales en sync_noche ──────────────────────────────────────
    _sep("Fase C · Mensuales desde sync_noche (max_age=168h)")
    try:
        resultado_c = _check_freshness_sources("mensual", max_age_h=168)
        for fuente, info in sorted(resultado_c.items()):
            if info["stale"] > 0:
                print(f"  ✓ {fuente}: procesaría {info['stale']} ubicación(es)")
            else:
                print(f"  — {fuente}: omitido (datos frescos)")
    except Exception as e:
        print(f"  ERROR: {e}")


# ── MENSUAL ───────────────────────────────────────────────────────────────────


def sim_mensual() -> None:
    _sep("SIMULACRO MENSUAL — 2026-08-01 03:00 UTC", "═")

    conn = _orig_get_conn()

    # ── Jobs data-driven ─────────────────────────────────────────────────────
    _sep("Loop data-driven · activacion_señales mensual")
    try:
        filas = conn.execute(
            """
            SELECT s.fuente, COUNT(*) as n, STRING_AGG(u.nombre, ', ' ORDER BY u.nombre) as locs
            FROM activacion_señales a
            JOIN señales s USING(señal_id)
            JOIN ubicaciones u USING(ubicacion_id)
            WHERE a.status IN ('contexto', 'active') AND a.periodicidad = 'mensual'
            GROUP BY s.fuente ORDER BY s.fuente
            """
        ).fetchall()
        if filas:
            for fuente, n, locs in filas:
                print(f"  {fuente}: {n} job(s) → {locs[:80]}")
        else:
            print("  (sin jobs en activacion_señales — se usa bootstrap vía config_fuentes)")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── Fuentes mensuales registradas ─────────────────────────────────────────
    _sep("Fuentes mensuales activas (fuentes table)")
    fuentes_mens = conn.execute(
        "SELECT fuente FROM fuentes WHERE periodicidad = 'mensual' AND activo = TRUE ORDER BY fuente"
    ).fetchall()
    for (f,) in fuentes_mens:
        print(f"  · {f}")

    # ── Esri Places (POIs) ────────────────────────────────────────────────────
    _sep("Esri Places — POIs que se actualizarían")
    try:
        locs = conn.execute(
            "SELECT nombre, ubicacion_id, lat, lon FROM ubicaciones "
            "WHERE activa = TRUE AND lat IS NOT NULL ORDER BY nombre"
        ).fetchall()
        pois_actuales = conn.execute(
            "SELECT ubicacion_id, COUNT(*) FROM puntos_interes WHERE activo = TRUE GROUP BY ubicacion_id"
        ).fetchall()
        pois_map = {uid: n for uid, n in pois_actuales}
        print(f"  {'Ubicación':<40}  {'POIs actuales':>13}  Acción")
        print(f"  {'─'*40}  {'─'*13}  {'─'*25}")
        for nombre, uid, lat, lon in locs:
            n_pois = pois_map.get(uid, 0)
            accion = "re-sincronizaría" if n_pois > 0 else "primera ingesta"
            print(f"  {nombre:<40}  {n_pois:>13}  {accion}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── Esri GeoEnrichment ────────────────────────────────────────────────────
    _sep("Esri GeoEnrichment — snapshots que se actualizarían")
    try:
        locs = conn.execute(
            "SELECT u.nombre, u.ubicacion_id, "
            "MAX(sg.ingerido_en) as ultimo_snapshot, COUNT(sg.señal_id) as n_feats "
            "FROM ubicaciones u "
            "LEFT JOIN snapshots_geo sg ON sg.ubicacion_id = u.ubicacion_id AND sg.vigente_hasta IS NULL "
            "WHERE u.activa = TRUE AND u.lat IS NOT NULL "
            "GROUP BY u.nombre, u.ubicacion_id "
            "ORDER BY u.nombre"
        ).fetchall()
        print(f"  {'Ubicación':<40}  {'Último snapshot':>17}  {'Feats':>6}  Acción")
        print(f"  {'─'*40}  {'─'*17}  {'─'*6}  {'─'*20}")
        for nombre, uid, ultimo, n_feats in locs:
            ult_str = str(ultimo)[:10] if ultimo else "nunca"
            accion = "actualización" if ultimo else "primera entrega"
            print(f"  {nombre:<40}  {ult_str:>17}  {n_feats or 0:>6}  {accion}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── Cruceros calendario ───────────────────────────────────────────────────
    _sep("Cruceros calendario — rango que se refrescaría")
    yr = FECHA_SIM.year
    print(f"  Rango: enero {yr-1} → diciembre {yr}")
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(fecha_inicio), MAX(fecha_inicio) FROM eventos WHERE evento_key = 'escala_crucero'"
        ).fetchone()
        if row and row[0]:
            print(f"  Escalas actuales en DB: {row[0]}  ({row[1]} → {row[2]})")
        else:
            print("  Sin escalas en DB aún.")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── INE / Metro / Puertos ─────────────────────────────────────────────────
    _sep("INE / Metro Madrid / Puertos — estado actual")
    for fuente, tabla, col_fecha in [
        ("ine_eoh", "valores_señales", None),
        ("metro_madrid", "valores_señales", None),
        ("puertos_estado", "valores_señales", None),
    ]:
        try:
            row = conn.execute(
                "SELECT COUNT(*), MAX(fecha) FROM valores_señales vs "
                "JOIN señales s USING(señal_id) WHERE s.fuente = ?",
                [fuente],
            ).fetchone()
            n, ultima = row if row else (0, None)
            if n:
                dias = (FECHA_SIM - (ultima if isinstance(ultima, date) else ultima.date())).days
                print(
                    f"  {fuente:<20}  {n:>7} registros  último={str(ultima)[:10]}  ({dias} días de lag)"
                )
            else:
                print(f"  {fuente:<20}  sin datos en DB — ingesta desde cero")
        except Exception as e:
            print(f"  {fuente}: {e}")


# ── Resumen de escrituras interceptadas ───────────────────────────────────────


def _print_write_summary() -> None:
    _sep("ESCRITURAS INTERCEPTADAS (no ejecutadas)", "═")
    if not _writes:
        print("  (ninguna — solo se realizaron lecturas)")
        return
    from collections import Counter

    verbs = Counter(w.split(":")[0].split("×")[0] for w in _writes)
    for verb, n in sorted(verbs.items()):
        print(f"  {verb}: {n} llamadas")
    print(f"\n  Total: {len(_writes)} operaciones de escritura bloqueadas")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t0 = time.time()

    # Importar get_conn ANTES de parchear para guardarlo
    from src.db.store import get_conn as _gc

    _orig_get_conn = _gc

    print("=" * _ANCHO)
    print(f"  DRY-RUN SIMULACRO  —  fecha simulada: {FECHA_SIM}")
    print("  DB: solo lectura  |  APIs: reales (sin Esri)")
    print("=" * _ANCHO)

    with patch("src.db.store.get_conn", side_effect=_make_dry_conn):
        sim_diario()
        sim_mensual()

    _print_write_summary()
    print(f"\nSimulacro completado en {time.time() - t0:.0f}s")
