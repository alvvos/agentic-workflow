"""
Cruceros — sincronización del calendario de escalas por puerto.

Fuente: WP-AJAX del puerto configurado (action=get_prevision_turistas_by_date, sin key).
Aplica a cualquier ubicación con source='cruceros' en location_source_config.

Configuración en location_source_config (source = 'cruceros'):
  {
    "ajax_url":    "https://www.puertomalaga.com/wp-admin/admin-ajax.php",
    "pais_codigo": "ES"
  }

Escribe en:
  store_calendario_org  — una fila por escala (barco, fecha, pasajeros)
  store_features_ext    — agregado diario: feature_key='n_pasajeros_crucero_dia'

CLI:
    python -m src.data_ingestion.diaria.cruceros                # sync mes actual
    python -m src.data_ingestion.diaria.cruceros --desde 2025-01
    python -m src.data_ingestion.diaria.cruceros --dry-run
    python -m src.data_ingestion.diaria.cruceros --force
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.diaria._common import is_fresh, write_sync_marker
from src.data_ingestion.mensual._common import ensure_feature_registry
from src.db.store import get_conn

SOURCE = "cruceros"
_FK_DIA = "n_pasajeros_crucero_dia"


# ── Config desde location_source_config ──────────────────────────────────────


def _get_configured_locations() -> list[tuple[str, str, str]]:
    """
    Devuelve [(location_uuid, ajax_url, pais_codigo), ...] para todas
    las ubicaciones activas con source='cruceros' en location_source_config.
    """
    rows = (
        get_conn()
        .execute(
            "SELECT location_uuid, params "
            "FROM location_source_config "
            "WHERE source = 'cruceros' AND activo = TRUE"
        )
        .fetchall()
    )
    result = []
    for loc_uuid, params_raw in rows:
        params = params_raw if isinstance(params_raw, dict) else json.loads(params_raw or "{}")
        ajax_url = params.get("ajax_url")
        if not ajax_url:
            continue
        pais_codigo = params.get("pais_codigo", "ES")
        result.append((loc_uuid, ajax_url, pais_codigo))
    return result


# ── Parser de la respuesta JSON ───────────────────────────────────────────────


def _fetch_month(month: int, year: int, ajax_url: str) -> list[dict]:
    """
    Llama al endpoint WP-AJAX del puerto para un mes/año dado.
    Devuelve lista de dicts con fecha (YYYY-MM-DD), barco, n_pasajeros.
    """
    resp = requests.post(
        ajax_url,
        data={"action": "get_prevision_turistas_by_date", "date": f"{month:02d}/{year}"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": ajax_url.replace("/wp-admin/admin-ajax.php", "/es/prevision-cruceros/"),
            "User-Agent": "Mozilla/5.0 (compatible; agentic-workflow/1.0)",
        },
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()  # list of lists; row 0 = headers

    escalas = []
    for row in rows[1:]:
        if len(row) < 5:
            continue
        fecha = _parse_arrival_date(row[4], month, year)
        if fecha is None:
            continue
        buque = re.sub(r"<[^>]+>", " ", row[0]).strip()
        n_pax = _parse_int(str(row[2]))
        escalas.append({"fecha": str(fecha), "barco": buque, "n_pasajeros": n_pax, "terminal": ""})
    return escalas


def _parse_arrival_date(entrada_salida: str, query_month: int, query_year: int) -> date | None:
    """
    col[4] = "DD/MM HH:MM<br>DD/MM HH:MM" — toma la fecha de llegada (primera parte).
    El año se infiere del mes consultado con lógica de ventana ±6 meses.
    """
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


def _parse_int(s: str) -> int | None:
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


# ── Escritura en DB ───────────────────────────────────────────────────────────


def ingestar_escalas(
    escalas: list[dict],
    location_uuid: str,
    pais_codigo: str = "ES",
    dry_run: bool = False,
) -> int:
    """
    Inserta escalas en store_calendario_org y agrega pasajeros diarios en store_features_ext.
    Idempotente. Devuelve el número de filas de calendario insertadas.
    """
    if not escalas:
        return 0

    if dry_run:
        return len(escalas)

    conn = get_conn()

    cal_rows = [
        (
            None,  # org_uuid: se resuelve via location_uuid en la app
            location_uuid,
            pais_codigo,
            "escala_crucero",
            e["fecha"],
            e["fecha"],
            json.dumps(
                {"barco": e.get("barco", ""), "n_pasajeros": e.get("n_pasajeros"), "terminal": ""},
                ensure_ascii=False,
            ),
            "cruceros",
            f"{location_uuid}:escala_crucero:{e['fecha']}:{e.get('barco', '')}",
        )
        for e in escalas
    ]

    conn.executemany(
        """INSERT INTO store_calendario_org
               (org_uuid, location_uuid, pais_codigo, evento_key,
                fecha_inicio, fecha_fin, metadata, fuente, source_key)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (source_key) DO UPDATE SET metadata = excluded.metadata""",
        cal_rows,
    )

    # Agregar pasajeros por día → store_features_ext
    daily: dict[str, float] = {}
    for e in escalas:
        pax = e.get("n_pasajeros")
        if pax and pax > 0:
            daily[e["fecha"]] = daily.get(e["fecha"], 0.0) + pax

    if daily:
        ensure_feature_registry(_FK_DIA, SOURCE, "turismo")
        conn.executemany(
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT (fecha, location_uuid, feature_key) "
            "DO UPDATE SET value = excluded.value, ingested_at = NOW()",
            [(f, location_uuid, _FK_DIA, v) for f, v in daily.items()],
        )

    return len(cal_rows)


# ── Sync ──────────────────────────────────────────────────────────────────────


def sync_months(
    location_uuid: str,
    ajax_url: str,
    pais_codigo: str = "ES",
    desde: tuple[int, int] | None = None,
    hasta: tuple[int, int] | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> int:
    """
    Descarga y persiste escalas para un rango de meses (ambos inclusivos).
    desde/hasta: (month, year). Por defecto: mes actual únicamente.
    Devuelve el total de escalas procesadas.
    """
    today = date.today()
    if hasta is None:
        hasta = (today.month, today.year)
    if desde is None:
        desde = hasta

    m, y = desde
    total = 0
    while (y, m) <= (hasta[1], hasta[0]):
        escalas = _fetch_month(m, y, ajax_url)
        if verbose:
            print(f"  {m:02d}/{y}: {len(escalas)} escalas", end="")
        if not dry_run and escalas:
            ingestar_escalas(escalas, location_uuid, pais_codigo)
        if verbose:
            print()
        total += len(escalas)
        m += 1
        if m > 12:
            m, y = 1, y + 1

    return total


# ── run() — interfaz estándar diaria ─────────────────────────────────────────


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,
    verbose: bool = True,
) -> dict[str, int]:
    locations = _get_configured_locations()
    if location_uuid is not None:
        locations = [(lu, url, pc) for lu, url, pc in locations if lu == location_uuid]

    result: dict[str, int] = {}
    today = date.today()

    for loc_uuid, ajax_url, pais_codigo in locations:
        if is_fresh(loc_uuid, SOURCE, max_age_hours):
            if verbose:
                print(f"  [cruceros] {loc_uuid[:8]}…: omitido (datos < {max_age_hours:.0f}h)")
            result[loc_uuid] = 0
            continue

        try:
            prev = (today.month - 1 or 12, today.year if today.month > 1 else today.year - 1)
            nxt = (today.month % 12 + 1, today.year if today.month < 12 else today.year + 1)
            n = sync_months(loc_uuid, ajax_url, pais_codigo, desde=prev, hasta=nxt, verbose=verbose)
            write_sync_marker(loc_uuid, SOURCE)
            if verbose:
                print(f"  [cruceros] {loc_uuid[:8]}…: {n} escalas en calendario")
            result[loc_uuid] = n
        except Exception as e:
            if verbose:
                print(f"  [cruceros] {loc_uuid[:8]}… ERROR — {e}")
            result[loc_uuid] = 0

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingestor calendario cruceros por puerto")
    parser.add_argument("--force", action="store_true", help="Ignora caché de frescura")
    parser.add_argument("--dry-run", action="store_true", help="Parsea sin escribir en DB")
    parser.add_argument(
        "--desde", default=None, metavar="YYYY-MM", help="Mes de inicio (ej: 2025-01)"
    )
    parser.add_argument("--location", metavar="UUID", help="Procesar solo esta location")
    args = parser.parse_args()

    locations = _get_configured_locations()
    if not locations:
        print(
            "[cruceros] No hay ubicaciones configuradas en location_source_config (source='cruceros')."
        )
        sys.exit(0)

    today = date.today()
    for loc_uuid, ajax_url, pais_codigo in locations:
        if args.location and loc_uuid != args.location:
            continue
        if args.desde:
            d = datetime.strptime(args.desde, "%Y-%m")
            desde = (d.month, d.year)
            hasta = (today.month, today.year)
        else:
            prev_month = today.month - 1 or 12
            prev_year = today.year if today.month > 1 else today.year - 1
            nxt_month = today.month % 12 + 1
            nxt_year = today.year if today.month < 12 else today.year + 1
            desde = (prev_month, prev_year)
            hasta = (nxt_month, nxt_year)

        sync_months(
            loc_uuid,
            ajax_url,
            pais_codigo,
            desde=desde,
            hasta=hasta,
            dry_run=args.dry_run,
        )
