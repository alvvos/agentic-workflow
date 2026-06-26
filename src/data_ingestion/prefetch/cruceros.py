"""
Puerto de Málaga — sincronización del calendario de cruceros.

Fuente: puertomalaga.com WP-AJAX (action=get_prevision_turistas_by_date, sin key)
Solo aplica a Málaga Muelle 1 (location_uuid fijo).

Escribe en:
  store_calendario_org  — una fila por escala (barco, fecha, pasajeros)
  store_features_ext    — agregado diario: feature_key='n_pasajeros_crucero_dia'

CLI:
    python -m src.data_ingestion.prefetch.cruceros                # sync mes actual
    python -m src.data_ingestion.prefetch.cruceros --desde 2025-01
    python -m src.data_ingestion.prefetch.cruceros --dry-run
    python -m src.data_ingestion.prefetch.cruceros --force
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.prefetch._common import is_fresh, write_sync_marker
from src.db.store import get_conn

_SOURCE = "cruceros"
_MALAGA_LOCATION_UUID = "67034276-0d01-4c90-a363-fa75699a19a4"
_MALAGA_ORG_UUID = "5c13b57d-782d-4458-911b-64cd40eebb55"
_PAIS_CODIGO = "ES"
_FEATURE_KEY = "n_pasajeros_crucero_dia"
_AJAX_URL = "https://www.puertomalaga.com/wp-admin/admin-ajax.php"


# ── Parser de la respuesta JSON ───────────────────────────────────────────────


def _fetch_month(month: int, year: int) -> list[dict]:
    """
    Llama a la API AJAX del Puerto de Málaga para un mes/año dado.
    Devuelve lista de dicts con fecha (YYYY-MM-DD), barco, n_pasajeros, naviera.
    """
    resp = requests.post(
        _AJAX_URL,
        data={"action": "get_prevision_turistas_by_date", "date": f"{month:02d}/{year}"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.puertomalaga.com/es/prevision-cruceros/",
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
        buque_raw = re.sub(r"<[^>]+>", " ", row[0]).strip()
        buque = buque_raw
        n_pax = _parse_int(str(row[2]))
        escalas.append(
            {
                "fecha": str(fecha),
                "barco": buque,
                "n_pasajeros": n_pax,
                "terminal": "",
            }
        )
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
            year -= 1  # mes muy posterior al consultado → año anterior (ej. nov en consulta de feb)
        elif diff < -6:
            year += 1  # mes muy anterior al consultado → año siguiente (ej. ene en consulta de dic)
        return date(year, month, day)
    except Exception:
        return None


def _parse_int(s: str) -> int | None:
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


# ── Escritura en DB ───────────────────────────────────────────────────────────


def ingestar_escalas(escalas: list[dict]) -> int:
    """
    Inserta escalas en store_calendario_org y agrega el total diario en store_features_ext.
    Idempotente. Devuelve el número de filas de calendario insertadas.
    """
    if not escalas:
        return 0

    conn = get_conn()

    cal_rows = [
        (
            _MALAGA_ORG_UUID,
            _MALAGA_LOCATION_UUID,
            _PAIS_CODIGO,
            "escala_crucero",
            e["fecha"],
            e["fecha"],
            json.dumps(
                {
                    "barco": e.get("barco", ""),
                    "n_pasajeros": e.get("n_pasajeros"),
                    "terminal": e.get("terminal", ""),
                },
                ensure_ascii=False,
            ),
            "puerto_malaga",
            f"{_MALAGA_LOCATION_UUID}:escala_crucero:{e['fecha']}:{e.get('barco', '')}",
        )
        for e in escalas
    ]

    conn.executemany(
        """INSERT INTO store_calendario_org
               (org_uuid, location_uuid, pais_codigo, evento_key,
                fecha_inicio, fecha_fin, metadata, fuente, source_key)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (source_key) DO UPDATE SET
               metadata = excluded.metadata""",
        cal_rows,
    )

    # Reagrega totales diarios para los días afectados (evita acumulación en re-runs)
    fechas = list({e["fecha"] for e in escalas})
    ph = ",".join(["?"] * len(fechas))
    totales = conn.execute(
        f"""SELECT fecha_inicio::text,
                   COALESCE(SUM(
                       CASE WHEN (metadata->>'n_pasajeros') ~ '^[0-9]+$'
                            THEN (metadata->>'n_pasajeros')::int ELSE 0 END
                   ), 0)
            FROM   store_calendario_org
            WHERE  location_uuid = ?
              AND  evento_key    = 'escala_crucero'
              AND  fecha_inicio::text IN ({ph})
            GROUP  BY fecha_inicio""",
        [_MALAGA_LOCATION_UUID] + fechas,
    ).fetchall()

    if totales:
        conn.executemany(
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT (fecha, location_uuid, feature_key) "
            "DO UPDATE SET value = excluded.value, ingested_at = NOW()",
            [(f, _MALAGA_LOCATION_UUID, _FEATURE_KEY, float(t)) for f, t in totales],
        )

    return len(cal_rows)


# ── Sync ──────────────────────────────────────────────────────────────────────


def sync_months(
    desde: tuple[int, int] | None = None,
    hasta: tuple[int, int] | None = None,
    dry_run: bool = False,
) -> int:
    """
    Descarga y persiste escalas para un rango de meses (ambos inclusivos).
    desde/hasta: (month, year). Por defecto: mes actual únicamente.
    dry_run: parsea sin escribir en DB.
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
        escalas = _fetch_month(m, y)
        print(f"  {m:02d}/{y}: {len(escalas)} escalas", end="")
        if not dry_run and escalas:
            ingestar_escalas(escalas)
        print()
        total += len(escalas)
        m += 1
        if m > 12:
            m, y = 1, y + 1

    return total


# ── Cobertura ─────────────────────────────────────────────────────────────────


def get_coverage(year: int | None = None) -> dict:
    where = f"AND EXTRACT(YEAR FROM fecha::date)::int = {year}" if year else ""
    row = (
        get_conn()
        .execute(
            f"""SELECT COUNT(*), MIN(fecha), MAX(fecha), SUM(value), AVG(value)
            FROM   store_features_ext
            WHERE  location_uuid = ? AND feature_key = ? {where}""",
            [_MALAGA_LOCATION_UUID, _FEATURE_KEY],
        )
        .fetchone()
    )
    return {
        "n_dias": row[0] or 0,
        "fecha_min": str(row[1]) if row[1] else None,
        "fecha_max": str(row[2]) if row[2] else None,
        "total_pasajeros": int(row[3] or 0),
        "media_diaria": round(float(row[4] or 0), 0),
    }


# ── run() — interfaz estándar prefetch ───────────────────────────────────────


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,
    verbose: bool = True,
) -> dict[str, int]:
    if location_uuid is not None and location_uuid != _MALAGA_LOCATION_UUID:
        return {}

    if is_fresh(_MALAGA_LOCATION_UUID, _SOURCE, max_age_hours):
        if verbose:
            print(f"  [cruceros] Málaga Muelle 1: omitido (datos < {max_age_hours:.0f}h)")
        return {_MALAGA_LOCATION_UUID: 0}

    try:
        today = date.today()
        # Sync mes anterior, actual y siguiente (cubre histórico reciente + previsión)
        prev = (today.month - 1 or 12, today.year if today.month > 1 else today.year - 1)
        nxt = (today.month % 12 + 1, today.year if today.month < 12 else today.year + 1)
        n = sync_months(desde=prev, hasta=nxt)
        write_sync_marker(_MALAGA_LOCATION_UUID, _SOURCE)
        if verbose:
            cov = get_coverage(year=today.year)
            print(
                f"  [cruceros] Málaga Muelle 1: {n} escalas  "
                f'({cov["n_dias"]}d en DB, {cov["total_pasajeros"]} pax {today.year})'
            )
        return {_MALAGA_LOCATION_UUID: n}
    except Exception as e:
        if verbose:
            print(f"  [cruceros] Málaga Muelle 1: ERROR — {e}")
        return {_MALAGA_LOCATION_UUID: 0}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prefetch cruceros Puerto de Málaga")
    parser.add_argument(
        "--desde",
        default=None,
        metavar="YYYY-MM",
        help="Mes de inicio (ej: 2025-01). Por defecto: mes actual",
    )
    parser.add_argument(
        "--hasta",
        default=None,
        metavar="YYYY-MM",
        help="Mes de fin (ej: 2026-12). Por defecto: mes actual",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parsea sin escribir en DB")
    parser.add_argument("--max-age", type=float, default=6, metavar="HORAS")
    parser.add_argument("--force", action="store_true", help="Fuerza descarga (--max-age 0)")
    args = parser.parse_args()

    def _parse_ym(s: str) -> tuple[int, int]:
        d = datetime.strptime(s, "%Y-%m")
        return d.month, d.year

    today = date.today()
    desde = _parse_ym(args.desde) if args.desde else (today.month, today.year)
    hasta = _parse_ym(args.hasta) if args.hasta else (today.month, today.year)

    if args.dry_run or args.desde or args.hasta:
        sync_months(desde=desde, hasta=hasta, dry_run=args.dry_run)
    else:
        run(max_age_hours=0 if args.force else args.max_age)
