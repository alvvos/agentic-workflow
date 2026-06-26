#!/usr/bin/env python3
"""
Seed de organización + ubicación + fact_visitas ficticias para probar el
pipeline de onboarding completo (Agentes 1-5) sin datos reales.

Genera 90 días de visitas sintéticas para que el Feature Evaluator pueda
ejecutar walk-forward con 3 splits (mínimo 50 días en fact_visitas).

Uso:
    python scripts/seed_demo_org.py           # inserta + lanza onboarding
    python scripts/seed_demo_org.py --solo-seed  # solo inserta datos, sin onboarding
    python scripts/seed_demo_org.py --limpiar    # elimina todos los registros demo

Los UUIDs son fijos para que el script sea idempotente.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Constantes ────────────────────────────────────────────────────────────────

ORG_UUID = "demo-org-es-0001"
LOC_UUID = "demo-loc-madrid-0001"
ZONE_UUID = "demo-zone-entrada-0001"

ORG_NOMBRE = "Demo Retail ES"
LOC_NOMBRE = "Demo Madrid La Vaguada (ficticia)"

# Coordenadas reales de CC La Vaguada — bbox ES pasa sin problema
LAT = 40.4655
LON = -3.7104

N_DIAS = 90  # suficiente para 3 splits en el walk-forward


# ── Seed de visitas sintéticas ────────────────────────────────────────────────


def _generar_visitas(hoy: date) -> list[tuple]:
    """
    90 días de visitas diarias para una tienda de moda en Gran Vía.
    Patrón semanal realista: pico viernes/sábado, valle domingo/lunes.
    """
    rng = random.Random(42)
    filas = []

    for i in range(N_DIAS, 0, -1):
        dia = hoy - timedelta(days=i)
        dow = dia.weekday()  # 0=lun … 6=dom

        # Visitas base por día de semana
        base = {0: 180, 1: 190, 2: 200, 3: 210, 4: 310, 5: 380, 6: 160}[dow]
        total = max(10, int(rng.gauss(base, base * 0.12)))

        unique = int(total * rng.uniform(0.62, 0.75))
        new_v = int(unique * rng.uniform(0.25, 0.40))

        # Distribución horaria (horas 10-21, pico 12-14 y 18-20)
        weights = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 7, 10, 10, 8, 7, 9, 11, 10, 7, 4, 2, 1, 0]
        hourly = []
        remaining = total
        for h, w in enumerate(weights):
            if h == 23:
                hourly.append(remaining)
            else:
                v = int(total * w / sum(weights) * rng.uniform(0.85, 1.15))
                v = min(v, remaining)
                hourly.append(v)
                remaining = max(0, remaining - v)

        dwell = round(rng.uniform(8.0, 28.0), 1)

        filas.append(
            (
                dia.isoformat(),
                ZONE_UUID,
                LOC_UUID,
                ORG_UUID,
                total,
                unique,
                new_v,
                round(unique * 1.05, 1),  # uv_7d
                round(unique * 1.10, 1),  # uv_28d
                round(unique * 1.08, 1),  # uv_month
                round(unique * 1.12, 1),  # uv_year
                round(rng.uniform(1.2, 1.8), 2),  # freq_7d
                round(rng.uniform(1.4, 2.2), 2),  # freq_28d
                round(rng.uniform(1.3, 2.0), 2),  # freq_month
                round(rng.uniform(1.5, 2.5), 2),  # freq_year
                dwell,
                str([]),  # dwell_hist
                str(hourly),  # hourly_visits
            )
        )

    return filas


# ── Operaciones DB ────────────────────────────────────────────────────────────


def seed(conn) -> None:
    hoy = date.today()

    preset_es = json.dumps(
        {
            "rebajas_invierno": True,
            "rebajas_verano": True,
            "black_friday": True,
            "cyber_monday": True,
            "navidad_compras": True,
            "reyes_compras": True,
            "san_valentin": True,
            "dia_madre": True,
            "buen_fin_mx": False,
            "dia_muertos": False,
            "independencia_mx": False,
            "dia_madre_mx": False,
            "regreso_clases_mx": False,
            "dia_nino_mx": False,
        }
    )

    conn.execute(
        "INSERT INTO dim_organizaciones (org_uuid, nombre, pais_codigo, config_calendario) "
        "VALUES (?,?,?,?::jsonb) ON CONFLICT (org_uuid) DO NOTHING",
        [ORG_UUID, ORG_NOMBRE, "ES", preset_es],
    )

    conn.execute(
        "INSERT INTO dim_ubicaciones "
        "(location_uuid, org_uuid, nombre, lat, lon, ciudad, provincia, pais_codigo, "
        " region_code, country_code, codigo_postal, direccion, activa) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (location_uuid) DO NOTHING",
        [
            LOC_UUID,
            ORG_UUID,
            LOC_NOMBRE,
            LAT,
            LON,
            "Madrid",
            "Madrid",
            "ES",
            "MD",
            "ES",
            "28029",
            "Av. de Monforte de Lemos, 36, Madrid",
            True,
        ],
    )

    conn.execute(
        "INSERT INTO dim_zonas "
        "(zone_uuid, location_uuid, nombre, hidden, zone_type, parent_zone_uuid, sort_order, last_zone) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (zone_uuid) DO NOTHING",
        [ZONE_UUID, LOC_UUID, "Entrada principal", False, "entrance", None, 1, True],
    )

    visitas = _generar_visitas(hoy)
    conn.executemany(
        """
        INSERT INTO fact_visitas
            (fecha, zone_uuid, location_uuid, org_uuid,
             total_visits, unique_visitors, new_visitors,
             uv_7d, uv_28d, uv_month, uv_year,
             freq_7d, freq_28d, freq_month, freq_year,
             dwell_time_min, dwell_hist, hourly_visits)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (fecha, zone_uuid) DO NOTHING
        """,
        visitas,
    )

    print(f"  org          : {ORG_NOMBRE} ({ORG_UUID})")
    print(f"  ubicación    : {LOC_NOMBRE} ({LOC_UUID})")
    print(f"  zona         : Entrada principal ({ZONE_UUID})")
    print(
        f"  fact_visitas : {len(visitas)} días insertados ({(hoy - timedelta(N_DIAS)).isoformat()} → {(hoy - timedelta(1)).isoformat()})"
    )


def limpiar(conn) -> None:
    conn.execute("DELETE FROM fact_visitas     WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM feature_flags    WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM feature_eval_results WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM store_features_ext   WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM store_geo_snapshots  WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM dim_zonas        WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM dim_ubicaciones  WHERE location_uuid = ?", [LOC_UUID])
    conn.execute("DELETE FROM dim_organizaciones WHERE org_uuid    = ?", [ORG_UUID])
    print("Demo eliminada de todas las tablas.")


# ── Entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    args = set(sys.argv[1:])
    from src.db.store import get_conn

    conn = get_conn()

    if "--limpiar" in args:
        limpiar(conn)
        return

    print("── Insertando datos demo ─────────────────────────────────")
    seed(conn)

    if "--solo-seed" in args:
        print("\nDatos insertados. Onboarding omitido (--solo-seed).")
        return

    print("\n── Lanzando pipeline de onboarding ──────────────────────")
    from src.onboarding.pipeline import onboarding_ubicacion

    ok = onboarding_ubicacion(LOC_UUID)
    print(f"\nOnboarding {'COMPLETO ✓' if ok else 'INCOMPLETO — revisa logs arriba'}")


if __name__ == "__main__":
    main()
