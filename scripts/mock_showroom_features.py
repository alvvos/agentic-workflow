#!/usr/bin/env python3
"""
Genera y persiste datos mock para Showroom (Gran Vía 48, Madrid).

Series temporales (store_features_ext):
  afluencia_metro_gran_via   — validaciones diarias estimadas Gran Vía L1/L5
  n_turistas_isocrona        — turistas estimados en isocrona 10 min

Eventos (store_calendario_org):
  estreno_callao             — estrenos en Cine Callao
  manifestacion_gran_via     — marchas y manifestaciones por Gran Vía
  concierto_wizink           — conciertos en WiZink Center
  festival_madrid            — eventos de ciudad (San Isidro, Orgullo, Noche en Blanco…)

Uso:
  python scripts/mock_showroom_features.py            # 180 días
  python scripts/mock_showroom_features.py --dias 90
  python scripts/mock_showroom_features.py --dry-run
  python scripts/mock_showroom_features.py --limpiar  # borra datos previos y regenera
"""
import argparse, json, os, random, sys
from datetime import date, timedelta
from math import sin, pi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

_SHOWROOM_UUID = "faf7d203-342e-44c6-96e3-1ed64d8252c3"

# ── Series temporales ─────────────────────────────────────────────────────────

_SERIES = {
    "afluencia_metro_gran_via": {"base_l": 12_400, "base_w": 7_800,  "amp": 0.10, "noise": 0.07},
    "n_turistas_isocrona":      {"base_l":  6_800, "base_w": 10_200, "amp": 0.30, "noise": 0.14},
}


def _serie_val(p, d: date, rng) -> float:
    es_w = d.weekday() >= 5
    base = p["base_w"] if es_w else p["base_l"]
    doy  = d.timetuple().tm_yday
    return max(0.0, round(base * (1 + p["amp"] * sin(2 * pi * (doy - 80) / 365) + rng.gauss(0, p["noise"]))))


# ── Eventos ───────────────────────────────────────────────────────────────────

def _sk(uid, key, extra=""):
    return f"{uid}:{key}:{extra}"


def _ev(key, fi, ff, titulo, desc, impacto, asistentes, fuente="mock"):
    return dict(key=key, fi=str(fi), ff=str(ff), titulo=titulo, desc=desc,
                impacto=impacto, asistentes=asistentes, fuente=fuente)


_EVENTS = [
    # ── Manifestaciones ───────────────────────────────────────────────────────
    _ev("manifestacion_gran_via", date(2026, 3, 8), date(2026, 3, 8),
        "8M · Marcha Internacional por los Derechos de la Mujer",
        "La marcha recorrió Gran Vía y Paseo del Prado. Afluencia masiva en toda la isocrona.",
        "alto", "800.000"),
    _ev("manifestacion_gran_via", date(2026, 5, 1), date(2026, 5, 1),
        "1 de Mayo · Manifestación Día del Trabajo",
        "Sindicatos CCOO y UGT convocaron desde Neptuno hasta la Puerta del Sol.",
        "alto", "200.000"),
    _ev("manifestacion_gran_via", date(2026, 4, 19), date(2026, 4, 19),
        "Marcha por la Vivienda",
        "Plataforma de Afectados por la Hipoteca. Concentración frente al Congreso, paso por Gran Vía.",
        "medio", "60.000"),
    _ev("manifestacion_gran_via", date(2026, 6, 5), date(2026, 6, 5),
        "Marcha por el Clima · Día Mundial del Medio Ambiente",
        "Convocada por Fridays for Future. Recorrido Sol–Gran Vía–Cibeles.",
        "medio", "40.000"),
    _ev("manifestacion_gran_via", date(2026, 7, 19), date(2026, 7, 19),
        "Manifestación Sanitaria · Defensa de la Sanidad Pública",
        "Marea Blanca. Concentración en Puerta del Sol con paso por Gran Vía.",
        "medio", "75.000"),
    # ── Orgullo / Festivales ──────────────────────────────────────────────────
    _ev("festival_madrid", date(2026, 6, 27), date(2026, 6, 28),
        "WorldPride Madrid 2026 · Desfile del Orgullo",
        "El desfile principal recorre Paseo de la Castellana y afluye a Gran Vía. El área queda cortada.",
        "alto", "2.000.000"),
    _ev("festival_madrid", date(2026, 5, 15), date(2026, 5, 17),
        "San Isidro 2026 · Festividades Patronales de Madrid",
        "Verbenas, conciertos gratuitos y atracciones populares en todo el centro histórico.",
        "alto", "500.000"),
    _ev("festival_madrid", date(2026, 5, 2), date(2026, 5, 2),
        "Fiesta de la Comunidad de Madrid",
        "Día festivo autonómico. Alta afluencia turística y de ocio en zona centro.",
        "medio", "120.000"),
    _ev("festival_madrid", date(2026, 3, 28), date(2026, 4, 4),
        "Semana Santa 2026",
        "Máxima afluencia turística del año. Procesiones en el centro con cierre de calles.",
        "alto", "1.200.000"),
    _ev("festival_madrid", date(2026, 10, 3), date(2026, 10, 3),
        "Noche en Blanco · Madrid",
        "Museos gratuitos, instalaciones artísticas y actuaciones en Gran Vía y Paseo del Prado.",
        "alto", "400.000"),
    _ev("festival_madrid", date(2026, 8, 15), date(2026, 8, 15),
        "Verbenas de La Paloma · Cierre Fiestas de Verano",
        "Último día festivo de agosto en Madrid. Máxima afluencia turística de la temporada.",
        "medio", "300.000"),
    # ── Conciertos WiZink ─────────────────────────────────────────────────────
    _ev("concierto_wizink", date(2026, 3, 14), date(2026, 3, 14),
        "Dua Lipa · Radical Optimism Tour", "Sold out 20.000 entradas. Picos en metro Ventas y Gran Vía.",
        "alto", "20.000"),
    _ev("concierto_wizink", date(2026, 4, 11), date(2026, 4, 11),
        "Coldplay · Music of the Spheres", "Sold out. Dos noches. Extra de metro desde Gran Vía.",
        "alto", "20.000"),
    _ev("concierto_wizink", date(2026, 4, 12), date(2026, 4, 12),
        "Coldplay · Music of the Spheres (Noche 2)", "Segunda fecha agotada.",
        "alto", "20.000"),
    _ev("concierto_wizink", date(2026, 5, 9), date(2026, 5, 9),
        "Rosalía · MOTOMAMI Tour Europe",
        "20.000 asistentes. Flujo intenso metro Gran Vía y Callao a partir de las 21h.",
        "alto", "20.000"),
    _ev("concierto_wizink", date(2026, 6, 13), date(2026, 6, 13),
        "Bad Bunny · Tour Más Fechas", "Sold out. Alta demanda de transporte.",
        "alto", "20.000"),
    _ev("concierto_wizink", date(2026, 7, 4), date(2026, 7, 4),
        "The Weeknd · After Hours til Dawn", "Sold out.",
        "alto", "20.000"),
    _ev("concierto_wizink", date(2026, 7, 18), date(2026, 7, 18),
        "Sabrina Carpenter · Short n' Sweet Tour", "Sold out.",
        "alto", "18.000"),
    _ev("concierto_wizink", date(2026, 9, 5), date(2026, 9, 5),
        "Billie Eilish · HIT ME HARD AND SOFT: The Tour",
        "Vuelta de la temporada. Primeras noches de septiembre.",
        "alto", "20.000"),
    # ── Estrenos Cine Callao ──────────────────────────────────────────────────
    _ev("estreno_callao", date(2026, 3, 6), date(2026, 3, 6),
        "Premiere — 'Avengers: Doomsday'", "Cola en Gran Vía desde las 19h. 14 salas agotadas.",
        "alto", "4.200"),
    _ev("estreno_callao", date(2026, 3, 20), date(2026, 3, 20),
        "Premiere — 'Paddington en Perú'", "Reposición del éxito navideño. Familiar.",
        "bajo", "1.800"),
    _ev("estreno_callao", date(2026, 4, 3), date(2026, 4, 3),
        "Premiere — 'Misión Imposible: El Ajuste Final'",
        "Premiere con Tom Cruise en Madrid. Corte parcial de Gran Vía.",
        "alto", "3.600"),
    _ev("estreno_callao", date(2026, 4, 17), date(2026, 4, 17),
        "Premiere — 'Minerva' (Alejandro Amenábar)",
        "Producción española. Alfombra roja en acceso principal de Callao.",
        "medio", "2.100"),
    _ev("estreno_callao", date(2026, 5, 1), date(2026, 5, 1),
        "Premiere — 'Lilo & Stitch' (live action)",
        "Estreno global Disney. Máxima ocupación en horario de tarde.",
        "medio", "3.000"),
    _ev("estreno_callao", date(2026, 5, 22), date(2026, 5, 22),
        "Premiere — 'Star Wars: The New Dawn'",
        "Colas desde Callao hasta Sol. Maratón de proyecciones 0h, 3h, 6h.",
        "alto", "4.800"),
    _ev("estreno_callao", date(2026, 6, 5), date(2026, 6, 5),
        "Premiere — 'Jurassic World: Rebirth'",
        "Premiere internacional en Madrid. Afluencia familiar intensa.",
        "medio", "2.900"),
    _ev("estreno_callao", date(2026, 6, 19), date(2026, 6, 19),
        "Premiere — 'Fast X: Part II'",
        "Franquicia con audiencia masiva. Colas registradas en Gran Vía.",
        "medio", "3.200"),
    _ev("estreno_callao", date(2026, 7, 10), date(2026, 7, 10),
        "Premiere — 'Superman: Legacy'",
        "Nuevo DC Universe. Expectación máxima. Evento nocturno con photocall.",
        "alto", "4.500"),
    _ev("estreno_callao", date(2026, 7, 24), date(2026, 7, 24),
        "Premiere — 'Minecraft: La Película (Vol. 2)'",
        "Éxito de taquilla. Horario extendido fin de semana.",
        "medio", "2.600"),
    _ev("estreno_callao", date(2026, 8, 7), date(2026, 8, 7),
        "Premiere — 'Avatar: Fire and Ash'",
        "Tercera entrega de Cameron. Mayor expectación del verano.",
        "alto", "5.100"),
]

_IMPACTO_COLORS = {"alto": "#e74c3c", "medio": "#f39c12", "bajo": "#27ae60"}
_KEY_ICONS = {
    "estreno_callao":        "🎬",
    "manifestacion_gran_via": "📢",
    "concierto_wizink":       "🎵",
    "festival_madrid":        "🏙️",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias",    type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limpiar", action="store_true")
    args = parser.parse_args()

    rng  = random.Random(42)
    hoy  = date.today()

    # Series temporales
    serie_rows = []
    for offset in range(args.dias, 0, -1):
        d = hoy - timedelta(days=offset)
        for fk, p in _SERIES.items():
            serie_rows.append((_SHOWROOM_UUID, fk, str(d), _serie_val(p, d, rng)))

    # Eventos
    cal_rows = []
    for ev in _EVENTS:
        meta = json.dumps({
            "titulo":       ev["titulo"],
            "descripcion":  ev["desc"],
            "impacto":      ev["impacto"],
            "asistentes":   ev["asistentes"],
            "icono":        _KEY_ICONS.get(ev["key"], "📍"),
        }, ensure_ascii=False)
        cal_rows.append((
            None,  # org_uuid — se rellena abajo
            _SHOWROOM_UUID,
            "ES",
            ev["key"],
            ev["fi"], ev["ff"],
            meta,
            ev["fuente"],
            _sk(_SHOWROOM_UUID, ev["key"], ev["fi"] + ev["titulo"][:20]),
        ))

    if args.dry_run:
        print(f"Series: {len(serie_rows)} filas | Eventos: {len(cal_rows)}")
        for ev in sorted(_EVENTS, key=lambda e: e["fi"])[-5:]:
            print(f"  {ev['fi']}  {_KEY_ICONS.get(ev['key'],'')} {ev['titulo']}")
        return

    from src.db.store import get_conn
    conn = get_conn()

    # Obtener org_uuid de Showroom
    org_row = conn.execute(
        "SELECT org_uuid FROM dim_ubicaciones WHERE location_uuid = ?",
        [_SHOWROOM_UUID],
    ).fetchone()
    org_uuid = org_row[0] if org_row else None

    if args.limpiar:
        conn.execute(
            "DELETE FROM store_calendario_org WHERE location_uuid = ? AND fuente = 'mock'",
            [_SHOWROOM_UUID],
        )
        conn.execute(
            "DELETE FROM store_features_ext WHERE location_uuid = ? AND feature_key IN (?,?)",
            [_SHOWROOM_UUID, "afluencia_metro_gran_via", "n_turistas_isocrona"],
        )
        print("Datos mock anteriores eliminados.")

    conn.executemany(
        "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT (fecha, location_uuid, feature_key) DO UPDATE SET value = excluded.value",
        [(r[2], r[0], r[1], r[3]) for r in serie_rows],
    )

    cal_rows_db = [
        (org_uuid, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8])
        for r in cal_rows
    ]
    conn.executemany(
        "INSERT INTO store_calendario_org "
        "(org_uuid, location_uuid, pais_codigo, evento_key, fecha_inicio, fecha_fin, metadata, fuente, source_key) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (source_key) DO UPDATE SET metadata = excluded.metadata",
        cal_rows_db,
    )

    print(f"OK — {len(serie_rows)} filas de serie + {len(cal_rows)} eventos escritos para Showroom.")


if __name__ == "__main__":
    main()
