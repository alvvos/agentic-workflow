"""
Conector de agendas via POST AJAX con respuesta tabular (WordPress u otros CMS).
Usado actualmente para escalas de cruceros (puertos con web WordPress).

Interfaz pública:
    TIPO = "agenda_ajax_tabla"
    sync(ubicacion, cfg, verbose) -> int
    sync_rango_meses(ubicacion_id, cfg, desde, hasta, dry_run, verbose) -> int
"""

from __future__ import annotations

import json as _json
import re
from datetime import date

from src.data_ingestion._common import ensure_feature_registry

TIPO = "agenda_ajax_tabla"


# ── Helpers internos ──────────────────────────────────────────────────────────


def _parse_arrival_date(entrada_salida: str, query_month: int, query_year: int):
    try:
        llegada = re.split(r"<br\s*/?>", entrada_salida, flags=re.I)[0].strip()
        m = re.match(r"(\d{1,2})/(\d{1,2})", llegada)
        if not m:
            return None
        day, month = int(m.group(1)), int(m.group(2))
        year = query_year
        diff = month - query_month
        if diff > 6:
            year -= 1
        elif diff < -6:
            year += 1
        return date(year, month, day)
    except Exception:
        return None


def _parse_int(s: str):
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


def _fetch_month(ajax_url: str, month: int, year: int, action: str) -> list[dict]:
    import requests

    resp = requests.post(
        ajax_url,
        data={"action": action, "date": f"{month:02d}/{year}"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": ajax_url.replace("/wp-admin/admin-ajax.php", "/es/prevision-cruceros/"),
            "User-Agent": "Mozilla/5.0 (compatible; agentic-workflow/1.0)",
        },
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()
    escalas = []
    for row in rows[1:]:
        if len(row) < 5:
            continue
        f = _parse_arrival_date(row[4], month, year)
        if f is None:
            continue
        buque = re.sub(r"<[^>]+>", " ", row[0]).strip()
        n_pax = _parse_int(str(row[2]))
        escalas.append({"fecha": str(f), "barco": buque, "n_pasajeros": n_pax, "terminal": ""})
    return escalas


def _ingestar_escalas(
    escalas: list[dict],
    ubicacion_id: str,
    pais_codigo: str,
    feature_key: str,
    categoria_evento: str,
    dry_run: bool = False,
) -> int:
    if not escalas or dry_run:
        return 0

    from src.db.store import get_conn

    conn = get_conn()
    cal_rows = [
        (
            None,
            ubicacion_id,
            pais_codigo,
            categoria_evento,
            e["fecha"],
            e["fecha"],
            _json.dumps(
                {
                    "barco": e.get("barco", ""),
                    "n_pasajeros": e.get("n_pasajeros"),
                    "terminal": "",
                },
                ensure_ascii=False,
            ),
            "cruceros",
            f"{ubicacion_id}:{categoria_evento}:{e['fecha']}:{e.get('barco', '')}",
        )
        for e in escalas
    ]
    conn.executemany(
        """INSERT INTO eventos
               (org_id, ubicacion_id, pais_codigo, evento_key,
                fecha_inicio, fecha_fin, metadata, fuente, clave_fuente)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (clave_fuente) DO UPDATE SET metadata = excluded.metadata""",
        cal_rows,
    )
    daily: dict[str, float] = {}
    for e in escalas:
        pax = e.get("n_pasajeros")
        if pax and pax > 0:
            daily[e["fecha"]] = daily.get(e["fecha"], 0.0) + pax
    if daily:
        ensure_feature_registry(feature_key, "cruceros", "turismo")
        conn.executemany(
            "INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT (fecha, ubicacion_id, señal_id) "
            "DO UPDATE SET valor = excluded.valor, ingerido_en = NOW()",
            [(f, ubicacion_id, feature_key, v) for f, v in daily.items()],
        )
    return len(cal_rows)


# ── Interfaz pública ──────────────────────────────────────────────────────────


def sync(ubicacion: dict, cfg: dict, verbose: bool = True) -> int:
    """
    Descarga escalas para los meses anterior, actual y siguiente.

    ubicacion: {ubicacion_id, nombre, lat, lon, pais_codigo, codigo_region, city}
    cfg: config efectiva — debe contener ajax_url, feature_key, categoria_evento, action.
    No llama a is_fresh() ni write_sync_marker() — los gestiona el orquestador.
    Devuelve el número de escalas procesadas.
    """
    ubicacion_id = ubicacion["ubicacion_id"]
    ajax_url = cfg.get("ajax_url") or ubicacion.get("ajax_url")
    if not ajax_url:
        if verbose:
            print(f"  [agenda_ajax_tabla] {ubicacion_id[:8]}…: sin ajax_url en cfg — omitido")
        return 0

    pais_codigo = cfg.get("pais_codigo", ubicacion.get("pais_codigo", "ES"))
    feature_key = cfg.get("feature_key", "n_pasajeros_crucero_dia")
    categoria_evento = cfg.get("categoria_evento", "escala_crucero")
    action = cfg.get("action", "get_prevision_turistas_by_date")

    today = date.today()
    prev = (today.month - 1 or 12, today.year if today.month > 1 else today.year - 1)
    nxt = (today.month % 12 + 1, today.year if today.month < 12 else today.year + 1)

    m, y = prev
    total = 0
    while (y, m) <= (nxt[1], nxt[0]):
        escalas = _fetch_month(ajax_url, m, y, action)
        if verbose:
            print(f"  [agenda_ajax_tabla] {m:02d}/{y}: {len(escalas)} escalas", end="")
        if escalas:
            _ingestar_escalas(escalas, ubicacion_id, pais_codigo, feature_key, categoria_evento)
        if verbose:
            print()
        total += len(escalas)
        m += 1
        if m > 12:
            m, y = 1, y + 1

    if verbose:
        print(f"  [agenda_ajax_tabla] {ubicacion_id[:8]}…: {total} escalas en calendario")
    return total


def sync_rango_meses(
    ubicacion_id: str,
    cfg: dict,
    desde: tuple[int, int] | None = None,
    hasta: tuple[int, int] | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> int:
    """
    Descarga y persiste escalas para un rango de meses.
    Función pública usada por sync_diaria.sync_cruceros_months y scripts/sync_mensual.py.

    desde/hasta: (month, year). Por defecto: mes actual únicamente.
    Devuelve el total de escalas procesadas.
    """
    ajax_url = cfg.get("ajax_url")
    if not ajax_url:
        if verbose:
            print(f"  [agenda_ajax_tabla] {ubicacion_id[:8]}…: sin ajax_url en cfg — omitido")
        return 0

    pais_codigo = cfg.get("pais_codigo", "ES")
    feature_key = cfg.get("feature_key", "n_pasajeros_crucero_dia")
    categoria_evento = cfg.get("categoria_evento", "escala_crucero")
    action = cfg.get("action", "get_prevision_turistas_by_date")

    today = date.today()
    if hasta is None:
        hasta = (today.month, today.year)
    if desde is None:
        desde = hasta

    m, y = desde
    total = 0
    while (y, m) <= (hasta[1], hasta[0]):
        escalas = _fetch_month(ajax_url, m, y, action)
        if verbose:
            print(f"  {m:02d}/{y}: {len(escalas)} escalas", end="")
        _ingestar_escalas(
            escalas, ubicacion_id, pais_codigo, feature_key, categoria_evento, dry_run
        )
        if verbose:
            print()
        total += len(escalas)
        m += 1
        if m > 12:
            m, y = 1, y + 1

    return total
