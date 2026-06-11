#!/usr/bin/env python3
"""
Genera y persiste datos mock para Showroom (Gran Vía 48, Madrid).

Fuentes de referencia:
  - CRTM 2025: Sol ~60 k val./día (1er puesto). Gran Vía y Callao estimados
    entre 25-35 k/día (intersección de dos líneas, zona comercial central).
  - Fechas de eventos: fuentes oficiales (Ayto. Madrid, madridorgullo.com,
    eldiario.es, songkick.com, cinescallao.es).

Series temporales (store_features_ext):
  afluencia_metro_gran_via  — validaciones diarias estación Gran Vía (L1/L5)
  afluencia_metro_callao    — validaciones diarias estación Callao (L3/L5)
  n_turistas_isocrona       — turistas estimados en isócrona 10 min (no metro)

Eventos (store_calendario_org):
  estreno_callao             — estrenos / premieres en Cines Callao (100 años en 2026)
  manifestacion_gran_via     — marchas y manifestaciones por Gran Vía
  concierto_wizink           — conciertos en WiZink Center (cap. ~17 500)
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
# Estimaciones CRTM 2025:
#   Sol (L1/L2/L3):        ~60 000 val./día — 1er puesto red metro
#   Gran Vía (L1/L5):      ~32 000 val./día — nodo comercial central
#   Callao (L3/L5):        ~24 000 val./día — plaza y acceso peatonal GV
#   Turistas isócrona 10': ~5 500 entre semana · ~8 200 fin de semana
_SERIES = {
    "afluencia_metro_gran_via": {"base_l": 32_000, "base_w": 26_000, "amp": 0.10, "noise": 0.07},
    "afluencia_metro_callao":   {"base_l": 24_000, "base_w": 20_000, "amp": 0.09, "noise": 0.07},
    "n_turistas_isocrona":      {"base_l":  5_500, "base_w":  8_200, "amp": 0.28, "noise": 0.12},
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


_KEY_FA_ICONS = {
    "estreno_callao":         "fas fa-film",
    "manifestacion_gran_via": "fas fa-bullhorn",
    "concierto_wizink":       "fas fa-music",
    "festival_madrid":        "fas fa-city",
    "escala_crucero":         "fas fa-ship",
}

_EVENTS = [
    # ── Manifestaciones ───────────────────────────────────────────────────────
    _ev("manifestacion_gran_via", date(2026, 3, 8), date(2026, 3, 8),
        "8M · Marcha Internacional por los Derechos de la Mujer",
        "Dos bloques: Atocha-Sevilla y Cibeles-Plaza de España vía Gran Vía. "
        "Inicio a las 12:00 h con corte total de la calle. "
        "Fuente: eldiario.es / Comisión 8M Madrid.",
        "alto", "400.000"),
    _ev("manifestacion_gran_via", date(2026, 5, 1), date(2026, 5, 1),
        "1 de Mayo · Manifestación Día del Trabajo",
        "Convocada por CCOO y UGT. Concentración en Neptuno con recorrido "
        "hasta Puerta del Sol pasando por Gran Vía. Reclama mejoras salariales "
        "y derechos laborales ante el incremento del coste de vida.",
        "alto", "150.000"),
    _ev("manifestacion_gran_via", date(2026, 4, 19), date(2026, 4, 19),
        "Marcha por la Vivienda",
        "Plataforma de Afectados por la Hipoteca. Concentración frente al Congreso, "
        "paso por Gran Vía. Reclama medidas urgentes contra la especulación "
        "y el alquiler abusivo.",
        "medio", "60.000"),
    _ev("manifestacion_gran_via", date(2026, 6, 5), date(2026, 6, 5),
        "Marcha por el Clima · Día Mundial del Medio Ambiente",
        "Convocada por Fridays for Future España. Recorrido Sol–Gran Vía–Cibeles. "
        "Exige cumplimiento de objetivos climáticos europeos y protección de ecosistemas.",
        "medio", "35.000"),
    _ev("manifestacion_gran_via", date(2026, 7, 19), date(2026, 7, 19),
        "Manifestación Sanitaria · Defensa de la Sanidad Pública",
        "Marea Blanca. Concentración en Puerta del Sol con paso por Gran Vía. "
        "Protesta contra recortes en atención primaria y listas de espera.",
        "medio", "70.000"),

    # ── Festividades y eventos de ciudad ──────────────────────────────────────
    _ev("festival_madrid", date(2026, 7, 4), date(2026, 7, 4),
        "Orgullo de Madrid 2026 · Desfile Estatal LGTBI+",
        "El desfile estatal parte de Atocha (Paseo del Prado) hacia Colón a las 18:00 h. "
        "Afluencia masiva en Gran Vía, Chueca y zona centro. Mayor movilización LGTBI+ de Europa. "
        "Festividades del 25 de junio al 5 de julio. Fuente: madridorgullo.com",
        "alto", "1.500.000"),
    _ev("festival_madrid", date(2026, 5, 7), date(2026, 5, 17),
        "San Isidro 2026 · Festividades Patronales de Madrid",
        "Verbenas, conciertos gratuitos y atracciones populares en Pradera de San Isidro, "
        "Plaza Mayor y Matadero. Día del patrón el 15 de mayo con fuegos artificiales. "
        "Artistas confirmados: Fangoria, Miguel Ríos y bandas de zarzuela. "
        "Fuente: Ayuntamiento de Madrid.",
        "alto", "600.000"),
    _ev("festival_madrid", date(2026, 5, 2), date(2026, 5, 2),
        "Día de la Comunidad de Madrid",
        "Festivo autonómico. Alta afluencia turística y de ocio en zona centro. "
        "Acceso gratuito a museos municipales y actividades en el Parque del Retiro.",
        "medio", "120.000"),
    _ev("festival_madrid", date(2026, 3, 27), date(2026, 4, 5),
        "Semana Santa 2026",
        "Más de 30 procesiones por el centro de Madrid. Epicentro en Puerta del Sol "
        "y Calle Mayor. Viernes Santo (3 de abril) con dos procesiones principales. "
        "Máxima afluencia turística del año con cierre de calles. "
        "Fuente: Ayuntamiento de Madrid.",
        "alto", "1.200.000"),
    _ev("festival_madrid", date(2026, 9, 12), date(2026, 9, 13),
        "Noche en Blanco 2026 · Madrid",
        "252 instituciones culturales con acceso gratuito de 21:00 h a 07:00 h. "
        "Museos, galerías e instalaciones artísticas en Gran Vía y Paseo del Prado. "
        "Fuente: Ayuntamiento de Madrid.",
        "alto", "400.000"),
    _ev("festival_madrid", date(2026, 8, 15), date(2026, 8, 15),
        "Verbenas de La Paloma · Cierre Fiestas de Verano",
        "Último festivo de agosto en Madrid. Máxima afluencia turística de la temporada "
        "estival. Gran Vía y Chueca como principales focos de actividad.",
        "medio", "250.000"),

    # ── Conciertos WiZink Center ──────────────────────────────────────────────
    _ev("concierto_wizink", date(2026, 3, 14), date(2026, 3, 14),
        "Dua Lipa · Radical Optimism Tour",
        "WiZink Center · 17 500 localidades. Afluencia intensa en metro Gran Vía "
        "y Ventas desde las 19:00 h.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 4, 11), date(2026, 4, 11),
        "Coldplay · Music of the Spheres World Tour — Noche 1",
        "Sold out · 17 500 entradas. Primera de dos noches consecutivas. "
        "Refuerzo de metro en L5 (Gran Vía–Ventas) a partir de las 23:00 h.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 4, 12), date(2026, 4, 12),
        "Coldplay · Music of the Spheres World Tour — Noche 2",
        "Segunda fecha. Dos noches consecutivas sold out en WiZink Center.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 5, 31), date(2026, 5, 31),
        "La Oreja de Van Gogh · Gira 30 Aniversario",
        "Fecha confirmada en WiZink Center. Sold out. "
        "El grupo vasco celebra 30 años de carrera con gira por España. "
        "Fuente: Songkick / WiZink Center.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 6, 13), date(2026, 6, 13),
        "Bad Bunny · Tour 2026",
        "Sold out. Artista urbano con mayor demanda en Europa en 2025–2026. "
        "Flujo intenso en metro Ventas y Gran Vía desde las 20:00 h.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 7, 4), date(2026, 7, 4),
        "The Weeknd · After Hours til Dawn Tour",
        "Coincide con el Desfile del Orgullo 2026. Picos excepcionales de "
        "afluencia en todo el transporte público del área central.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 7, 18), date(2026, 7, 18),
        "Sabrina Carpenter · Short n' Sweet Tour",
        "17 000 localidades. Audiencia juvenil con alta concentración en metro "
        "Gran Vía y Callao tarde-noche.",
        "alto", "17.000"),
    _ev("concierto_wizink", date(2026, 9, 5), date(2026, 9, 5),
        "Billie Eilish · HIT ME HARD AND SOFT: The Tour",
        "Apertura de la temporada de otoño en WiZink Center. Sold out.",
        "alto", "17.500"),
    _ev("concierto_wizink", date(2026, 9, 22), date(2026, 9, 22),
        "La Oreja de Van Gogh · Segunda fecha Madrid",
        "Segunda fecha confirmada por alta demanda. Fuente: Songkick.",
        "alto", "17.500"),

    # ── Estrenos Cines Callao ─────────────────────────────────────────────────
    # Cines Callao cumple 100 años en 2026 (inauguración: 25 diciembre 1926).
    _ev("estreno_callao", date(2026, 3, 6), date(2026, 3, 6),
        "Premiere — Avengers: Doomsday (Marvel Studios)",
        "Estreno global simultáneo. Cola en Gran Vía desde las 19:00 h. "
        "Pases de medianoche agotados. Mayor estreno de Marvel desde Endgame.",
        "alto", "4.200"),
    _ev("estreno_callao", date(2026, 4, 3), date(2026, 4, 4),
        "Premiere — Misión Imposible: The Final Reckoning",
        "Paramount Pictures. Tom Cruise presente en Madrid para la premiere. "
        "Corte parcial de Gran Vía para alfombra roja. "
        "Pases especiales Jueves y Viernes Santo.",
        "alto", "3.600"),
    _ev("estreno_callao", date(2026, 4, 17), date(2026, 4, 17),
        "Premiere — Minerva (dir. Alejandro Amenábar)",
        "Producción española con alfombra roja en la Plaza de Callao. "
        "Gran expectación por el regreso de Amenábar al thriller histórico.",
        "medio", "2.100"),
    _ev("estreno_callao", date(2026, 5, 22), date(2026, 5, 22),
        "Premiere — Star Wars: The New Dawn",
        "Colas desde Callao hasta Sol. Pases especiales a las 00:00, 03:00 y 06:00 h. "
        "Afluencia nocturna excepcional en Gran Vía.",
        "alto", "4.800"),
    _ev("estreno_callao", date(2026, 6, 5), date(2026, 6, 5),
        "Premiere — Jurassic World: Rebirth (Universal Pictures)",
        "Premiere internacional en Madrid. Afluencia familiar intensa. "
        "Cola previa en la Plaza de Callao.",
        "medio", "2.900"),
    _ev("estreno_callao", date(2026, 7, 10), date(2026, 7, 10),
        "Premiere — Superman: Legacy (DC Studios)",
        "Nuevo universo DC con James Gunn. Expectación máxima. "
        "Photocall nocturno en Gran Vía con presencia de actores.",
        "alto", "4.500"),
    _ev("estreno_callao", date(2026, 8, 7), date(2026, 8, 7),
        "Premiere — Avatar: Fire and Ash (James Cameron)",
        "Tercera entrega. Proyección en formato IMAX y Dolby Atmos. "
        "Mayor expectación del verano. Afluencia de toda la Comunidad.",
        "alto", "5.100"),
    _ev("estreno_callao", date(2026, 9, 18), date(2026, 9, 18),
        "Cines Callao · Gala Centenario 1926–2026",
        "Evento de gala por el centenario del histórico cine de Gran Vía, inaugurado "
        "el 25 de diciembre de 1926. Alfombra roja, orquesta en directo y proyección "
        "especial. Presencia de autoridades y figuras del cine español.",
        "alto", "1.200"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias",    type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limpiar", action="store_true")
    args = parser.parse_args()

    rng  = random.Random(42)
    hoy  = date.today()

    serie_rows = []
    for offset in range(args.dias, 0, -1):
        d = hoy - timedelta(days=offset)
        for fk, p in _SERIES.items():
            serie_rows.append((_SHOWROOM_UUID, fk, str(d), _serie_val(p, d, rng)))

    cal_rows = []
    for ev in _EVENTS:
        meta = json.dumps({
            "titulo":       ev["titulo"],
            "descripcion":  ev["desc"],
            "impacto":      ev["impacto"],
            "asistentes":   ev["asistentes"],
            "icono_fa":     _KEY_FA_ICONS.get(ev["key"], "fas fa-calendar"),
        }, ensure_ascii=False)
        cal_rows.append((
            None,
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
            print(f"  {ev['fi']}  {ev['titulo']}")
        return

    from src.db.store import get_conn
    conn = get_conn()

    # Registrar feature_keys (FK constraint en store_features_ext)
    for fk in _SERIES:
        conn.execute(
            "INSERT INTO feature_registry (feature_key, source, categoria) "
            "VALUES (?, 'mock', 'ext_area') "
            "ON CONFLICT (feature_key) DO NOTHING",
            [fk],
        )

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
        fk_list = list(_SERIES.keys())
        placeholders = ",".join(["?" for _ in fk_list])
        conn.execute(
            f"DELETE FROM store_features_ext "
            f"WHERE location_uuid = ? AND feature_key IN ({placeholders})",
            [_SHOWROOM_UUID] + fk_list,
        )
        # Limpiar también clave antigua si existe
        conn.execute(
            "DELETE FROM store_features_ext "
            "WHERE location_uuid = ? AND feature_key = 'afluencia_metro_gran_via_l1l5'",
            [_SHOWROOM_UUID],
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
