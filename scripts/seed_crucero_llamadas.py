"""
Crea la tabla store_crucero_llamadas y siembra datos mock para Málaga Muelle 1
(2024-2026), incluyendo nombres de barco, operador y pasajeros.

También rellena store_features_ext.n_pasajeros_crucero_dia para 2024-2025
(2026 ya existe desde la migración anterior).

Uso:
  venv/bin/python scripts/seed_crucero_llamadas.py            # BD local
  DB_PORT=5433 venv/bin/python scripts/seed_crucero_llamadas.py  # prod vía túnel
"""
import os
import sys
import random
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
import psycopg

MALAGA_UUID = '67034276-0d01-4c90-a363-fa75699a19a4'

BARCOS = [
    ("MSC Grandiosa",        "MSC Cruceros",        6334),
    ("MSC Bellissima",       "MSC Cruceros",        5686),
    ("MSC Virtuosa",         "MSC Cruceros",        6334),
    ("MSC Splendida",        "MSC Cruceros",        4363),
    ("Costa Fascinosa",      "Costa Cruceros",      3800),
    ("Costa Diadema",        "Costa Cruceros",      4947),
    ("Costa Favolosa",       "Costa Cruceros",      3800),
    ("Harmony of the Seas",  "Royal Caribbean",     5479),
    ("Voyager of the Seas",  "Royal Caribbean",     3800),
    ("Norwegian Getaway",    "Norwegian Cruise",    3963),
    ("Norwegian Pearl",      "Norwegian Cruise",    2394),
    ("AIDAsol",              "AIDA Cruises",        2174),
    ("AIDAprima",            "AIDA Cruises",        3286),
    ("AIDAmar",              "AIDA Cruises",        2194),
    ("Celebrity Equinox",    "Celebrity Cruises",   2850),
    ("Celebrity Apex",       "Celebrity Cruises",   3260),
    ("P&O Britannia",        "P&O Cruises",         3647),
    ("P&O Iona",             "P&O Cruises",         5200),
    ("Carnival Glory",       "Carnival",            2974),
    ("TUI Marella Explorer", "TUI Cruises",         1814),
    ("Koningsdam",           "Holland America",     2650),
    ("Silver Cloud",         "Silversea",            260),
]


def _season_prob(d: date) -> float:
    m = d.month
    if m in (6, 7, 8, 9):    return 0.55
    if m in (4, 5, 10):       return 0.38
    if m in (3, 11):          return 0.18
    return 0.07


def _generate_calls(year: int, rng: random.Random) -> list:
    calls = []
    d = date(year, 1, 1)
    while d <= date(year, 12, 31):
        if rng.random() < _season_prob(d):
            n = rng.randint(1, 3 if d.month in (6, 7, 8) else 2)
            used = set()
            for _ in range(n):
                idx = rng.randint(0, len(BARCOS) - 1)
                while idx in used:
                    idx = rng.randint(0, len(BARCOS) - 1)
                used.add(idx)
                barco, operador, base_pax = BARCOS[idx]
                pax = int(base_pax * rng.uniform(0.82, 1.08))
                calls.append((d, barco, operador, pax))
        d += timedelta(days=1)
    return calls


def main():
    port = int(os.getenv('DB_PORT', 5432))
    conn = psycopg.connect(
        host='localhost', port=port,
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
    )

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS store_crucero_llamadas (
                id            SERIAL PRIMARY KEY,
                fecha         DATE        NOT NULL,
                location_uuid TEXT        NOT NULL,
                nombre_barco  TEXT        NOT NULL,
                operador      TEXT,
                n_pasajeros   INTEGER,
                terminal      TEXT        DEFAULT 'Muelle 1',
                ingested_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_crucero_loc_fecha
            ON store_crucero_llamadas (location_uuid, fecha)
        """)
        cur.execute(
            "DELETE FROM store_crucero_llamadas WHERE location_uuid = %s",
            [MALAGA_UUID],
        )

    rng = random.Random(42)
    all_calls: list = []
    for yr in (2024, 2025, 2026):
        all_calls.extend(_generate_calls(yr, rng))

    with conn.cursor() as cur:
        for fecha, barco, operador, pax in all_calls:
            cur.execute("""
                INSERT INTO store_crucero_llamadas
                    (fecha, location_uuid, nombre_barco, operador, n_pasajeros)
                VALUES (%s, %s, %s, %s, %s)
            """, [fecha, MALAGA_UUID, barco, operador, pax])
    print(f"  {len(all_calls)} llamadas de crucero insertadas")

    # Back-fill 2024-2025 daily aggregates in store_features_ext
    from collections import defaultdict
    daily: defaultdict = defaultdict(float)
    for fecha, _, _, pax in all_calls:
        if fecha.year in (2024, 2025):
            daily[fecha] += pax

    with conn.cursor() as cur:
        for fecha, total in daily.items():
            cur.execute("""
                INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value)
                VALUES (%s, %s, 'n_pasajeros_crucero_dia', %s)
                ON CONFLICT (fecha, location_uuid, feature_key)
                DO UPDATE SET value = EXCLUDED.value
            """, [fecha, MALAGA_UUID, total])
    print(f"  {len(daily)} días 2024-2025 de n_pasajeros_crucero_dia actualizados")

    conn.commit()
    conn.close()
    print("Hecho.")


if __name__ == '__main__':
    main()
