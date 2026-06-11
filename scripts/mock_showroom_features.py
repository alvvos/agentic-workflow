#!/usr/bin/env python3
"""
Genera y persiste series temporales mock para Showroom (Gran Vía 48, Madrid).

Features simuladas:
  afluencia_metro_gran_via   — validaciones diarias estimadas en estación Gran Vía (L1/L5)
  n_turistas_isocrona        — turistas estimados en isocrona 10 min a pie

Datos plausibles basados en:
  - CRTM media anual líneas 1/5 nodo Gran Vía: ~12 000 validaciones/día laborable
  - Gran Vía recibe ~25 M turistas/año → ~8 000 turistas/día en la isocrona 10 min

Uso:
  python scripts/mock_showroom_features.py            # últimos 90 días
  python scripts/mock_showroom_features.py --dias 180
  python scripts/mock_showroom_features.py --dry-run
"""
import argparse
import os
import random
import sys
from datetime import date, timedelta
from math import sin, pi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

_SHOWROOM_UUID = "faf7d203-342e-44c6-96e3-1ed64d8252c3"

_FEATURES = {
    "afluencia_metro_gran_via": {
        "base_laboral": 12_400,
        "base_finde":    7_800,
        "amplitud_anual": 0.12,
        "ruido":          0.08,
    },
    "n_turistas_isocrona": {
        "base_laboral":  7_200,
        "base_finde":   10_500,
        "amplitud_anual": 0.30,
        "ruido":          0.14,
    },
}


def _generar_valor(feat_params: dict, d: date, rng: random.Random) -> float:
    es_finde = d.weekday() >= 5
    base = feat_params["base_finde"] if es_finde else feat_params["base_laboral"]
    # Estacionalidad anual (verano +, enero -)
    dia_año = d.timetuple().tm_yday
    estac = feat_params["amplitud_anual"] * sin(2 * pi * (dia_año - 80) / 365)
    ruido = rng.gauss(0, feat_params["ruido"])
    return max(0.0, round(base * (1 + estac + ruido)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias",    type=int, default=90)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rng  = random.Random(42)
    hoy  = date.today()
    rows = []

    for offset in range(args.dias, 0, -1):
        d = hoy - timedelta(days=offset)
        for fk, params in _FEATURES.items():
            rows.append((_SHOWROOM_UUID, fk, str(d), _generar_valor(params, d, rng)))

    if args.dry_run:
        for uuid, fk, fecha, val in rows[-10:]:
            print(f"  {fecha}  {fk:<30}  {val:>8,.0f}")
        print(f"... ({len(rows)} filas totales, dry-run — no se escribe nada)")
        return

    from src.db.store import get_conn
    conn = get_conn()

    conn.executemany(
        "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT (fecha, location_uuid, feature_key) DO UPDATE SET value = excluded.value",
        [(r[2], r[0], r[1], r[3]) for r in rows],
    )
    print(f"OK — {len(rows)} filas escritas para Showroom ({args.dias} días).")
    for fk in _FEATURES:
        n = sum(1 for r in rows if r[1] == fk)
        print(f"  {fk}: {n} días")


if __name__ == "__main__":
    main()
