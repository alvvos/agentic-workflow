"""
Puerto de Málaga — cruise ship schedule ingestion.

Stores results in two places:
  store_calendario_org  — one row per call (ship name, arrival date, n_passengers)
  store_features_ext    — daily aggregate: feature_key='n_pasajeros_crucero_dia'

Feature registry entry (puerto_malaga / testing) is created by seed.py.
To promote to 'active', compare WMAPE before/after and call:
    activate_cruceros_feature()

Public data source: puertodemalaga.es/cruceros/
The port publishes a yearly schedule (PDF + HTML table) with:
  - Ship name, date, arrival/departure times, terminal, estimated passengers

Usage
-----
  # Auto-fetch current year schedule:
  from src.data_ingestion.ingesta_cruceros import sync_schedule
  inserted = sync_schedule(year=2026)

  # Manual import from a dict list (e.g., after scraping a PDF):
  from src.data_ingestion.ingesta_cruceros import ingestar_escalas
  ingestar_escalas([
      {'fecha': '2026-06-15', 'barco': 'MSC Grandiosa', 'n_pasajeros': 4888, 'terminal': 'T1'},
      ...
  ])
"""
import json
import re
from datetime import date, datetime
from typing import Optional
from pathlib import Path

import requests

from src.db.store import get_conn

_MALAGA_LOCATION_UUID = '67034276-0d01-4c90-a363-fa75699a19a4'
_MALAGA_ORG_UUID      = '5c13b57d-782d-4458-911b-64cd40eebb55'
_PAIS_CODIGO          = 'ES'
_FEATURE_KEY          = 'n_pasajeros_crucero_dia'

# Puerto de Málaga cruceros schedule — HTML table format
# Adjust selectors if the site redesigns.  The table has columns:
#   Fecha | Buque | Procedencia | Destino | T.Llegada | T.Salida | Terminal | Pasajeros
_SCHEDULE_URL = 'https://www.puertodemalaga.es/cruceros/escalas-previstas/'


# ── HTML parser ───────────────────────────────────────────────────────────────

def _parse_schedule_html(html: str) -> list[dict]:
    """
    Parse the Puerto de Málaga schedule HTML table.
    Returns a list of dicts: {fecha, barco, n_pasajeros, terminal}.
    Adjust column indices if the site changes layout.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise ImportError("Install beautifulsoup4: pip install beautifulsoup4")

    soup = BeautifulSoup(html, 'html.parser')
    rows = []

    for table in soup.find_all('table'):
        for tr in table.find_all('tr')[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            if len(cells) < 4:
                continue
            try:
                fecha_raw = cells[0]
                barco     = cells[1]
                terminal  = cells[7] if len(cells) > 7 else ''
                pax_raw   = cells[7] if len(cells) == 8 else (cells[6] if len(cells) == 7 else '')

                # Parse date (DD/MM/YYYY or YYYY-MM-DD)
                fecha = _parse_date(fecha_raw)
                if fecha is None:
                    continue

                # Parse passenger count (may have dots as thousands separator)
                n_pasajeros = _parse_int(pax_raw)

                rows.append({
                    'fecha': str(fecha),
                    'barco': barco,
                    'n_pasajeros': n_pasajeros,
                    'terminal': terminal,
                })
            except Exception:
                continue

    return rows


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(s: str) -> Optional[int]:
    s = re.sub(r'[^\d]', '', s)
    return int(s) if s else None


# ── DuckDB write ──────────────────────────────────────────────────────────────

def ingestar_escalas(escalas: list[dict]) -> int:
    """
    Insert cruise calls into store_calendario_org and aggregate daily sums
    into store_features_ext (feature_key='n_pasajeros_crucero_dia').

    Each dict in escalas must have: fecha (str YYYY-MM-DD), barco (str).
    Optional: n_pasajeros (int), terminal (str).

    Returns the number of new calendar rows inserted.
    """
    if not escalas:
        return 0

    conn = get_conn()

    # 1. Insert individual calls into store_calendario_org
    cal_rows = []
    for e in escalas:
        barco = e.get('barco', '')
        meta = json.dumps({
            'barco':       barco,
            'n_pasajeros': e.get('n_pasajeros'),
            'terminal':    e.get('terminal', ''),
        })
        # Deterministic dedup key: location + event + date + ship
        source_key = f"{_MALAGA_LOCATION_UUID}:escala_crucero:{e['fecha']}:{barco}"
        cal_rows.append((
            _MALAGA_ORG_UUID,
            _MALAGA_LOCATION_UUID,
            _PAIS_CODIGO,
            'escala_crucero',
            e['fecha'],
            e['fecha'],
            meta,
            'puerto_malaga',
            source_key,
        ))

    conn.executemany(
        """
        INSERT INTO store_calendario_org
            (org_uuid, location_uuid, pais_codigo, evento_key,
             fecha_inicio, fecha_fin, metadata, fuente, source_key)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT (source_key) DO NOTHING
        """,
        cal_rows,
    )

    # 2. Aggregate to daily totals and upsert into store_features_ext
    daily: dict[str, int] = {}
    for e in escalas:
        pax = e.get('n_pasajeros') or 0
        daily[e['fecha']] = daily.get(e['fecha'], 0) + pax

    # Recompute daily totals from ALL stored calls for affected dates (avoids accumulation)
    affected = list(daily.keys())
    if affected:
        placeholders = ','.join('?' * len(affected))
        conn.execute(
            f"DELETE FROM store_features_ext WHERE location_uuid=? AND feature_key=? AND CAST(fecha AS TEXT) IN ({placeholders})",
            [_MALAGA_LOCATION_UUID, _FEATURE_KEY] + affected,
        )

    ext_rows = [
        (fecha, _MALAGA_LOCATION_UUID, _FEATURE_KEY, float(total))
        for fecha, total in daily.items()
    ]
    conn.executemany(
        "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) VALUES (?,?,?,?)",
        ext_rows,
    )

    return len(cal_rows)


# ── HTTP fetch ────────────────────────────────────────────────────────────────

def sync_schedule(year: Optional[int] = None, dry_run: bool = False) -> int:
    """
    Fetch the schedule from puertodemalaga.es and persist to DuckDB.

    year: filter to a specific year (None = accept any date in the response).
    dry_run: parse and return results without writing to DB.
    Returns the number of rows inserted (0 on dry_run).
    """
    try:
        resp = requests.get(_SCHEDULE_URL, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; agentic-workflow/1.0)',
        })
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f'Failed to fetch schedule: {exc}') from exc

    escalas = _parse_schedule_html(resp.text)

    if year is not None:
        escalas = [e for e in escalas if e['fecha'].startswith(str(year))]

    if dry_run:
        print(f'Dry run: {len(escalas)} escalas parsed, not written.')
        for e in escalas[:5]:
            print(f"  {e['fecha']} — {e['barco']} ({e['n_pasajeros']} pax) — {e['terminal']}")
        return 0

    return ingestar_escalas(escalas)


# ── Feature gate helpers ──────────────────────────────────────────────────────

def get_coverage(year: Optional[int] = None) -> dict:
    """Returns stats about what's stored in store_features_ext for this feature."""
    conn = get_conn(read_only=True)
    where = f"AND YEAR(CAST(fecha AS DATE)) = {year}" if year else ''
    row = conn.execute(f"""
        SELECT COUNT(*), MIN(fecha), MAX(fecha), SUM(value), AVG(value)
        FROM store_features_ext
        WHERE location_uuid = ? AND feature_key = ? {where}
    """, [_MALAGA_LOCATION_UUID, _FEATURE_KEY]).fetchone()
    return {
        'n_dias': row[0],
        'fecha_min': str(row[1]),
        'fecha_max': str(row[2]),
        'total_pasajeros': row[3],
        'media_diaria': round(row[4] or 0, 0),
    }


def activate_cruceros_feature() -> None:
    """Promote n_pasajeros_crucero_dia from testing → active in feature_registry."""
    conn = get_conn()
    conn.execute(
        "UPDATE feature_registry SET status='active' WHERE feature_key=?",
        [_FEATURE_KEY],
    )
    print(f"'{_FEATURE_KEY}' → active")
