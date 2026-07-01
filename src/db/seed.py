"""
One-time migration: existing JSON / cache files → PostgreSQL.
Idempotent — uses ON CONFLICT DO NOTHING throughout.

Run after `docker compose up -d db`:
    cd /path/to/agentic-workflow
    python -m src.db.seed
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.db.store import get_conn

_DATA = Path(__file__).parent.parent / "data"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")

# ── helpers ───────────────────────────────────────────────────────────────────

_COUNTRY_MAP = {
    "España": "ES",
    "Spain": "ES",
    "México": "MX",
    "Mexico": "MX",
    "Estados Unidos": "US",
    "USA": "US",
    "United States": "US",
}


def _pais(loc: dict) -> str:
    if loc.get("country_code"):
        return loc["country_code"].upper()
    by_name = _COUNTRY_MAP.get(loc.get("country", ""), "")
    if by_name:
        return by_name
    # Fallback: sniff the address string for country keywords
    addr = (loc.get("address") or "").lower()
    if any(k in addr for k in ("méxico", "mexico", "cdmx", "ciudad de méxico", "ciudad de mexico")):
        return "MX"
    if any(
        k in addr
        for k in ("españa", "spain", "madrid", "barcelona", "málaga", "malaga", "valencia")
    ):
        return "ES"
    return "XX"


# Supercalendario config presets stored with each org so the app can read it
# without importing supercalendario.py from the DB layer.
_PRESET_ES = {
    "rebajas_invierno": True,
    "rebajas_verano": True,
    "black_friday": True,
    "cyber_monday": True,
    "navidad_compras": True,
    "reyes_compras": True,
    "san_valentin": True,
    "dia_madre": True,
    # MX off
    "buen_fin_mx": False,
    "dia_muertos": False,
    "independencia_mx": False,
    "dia_madre_mx": False,
    "regreso_clases_mx": False,
    "dia_nino_mx": False,
}

_PRESET_MX = {
    "rebajas_invierno": False,
    "rebajas_verano": False,
    "black_friday": False,  # replaced by buen_fin_mx
    "cyber_monday": True,
    "navidad_compras": True,
    "reyes_compras": True,
    "san_valentin": True,
    "dia_madre": False,  # ES = first Sunday May; MX = May 10 fixed
    # MX on
    "buen_fin_mx": True,
    "dia_muertos": True,
    "independencia_mx": True,
    "dia_madre_mx": True,
    "regreso_clases_mx": True,
    "dia_nino_mx": True,
}

_PRESETS = {"ES": _PRESET_ES, "MX": _PRESET_MX}


# ── seeders ───────────────────────────────────────────────────────────────────


def seed_ubicaciones() -> dict:
    conn = get_conn()
    raw = json.loads((_DATA / "todas_las_ubicaciones.json").read_text("utf-8"))

    orgs, locs, zonas = [], [], []
    for org in raw:
        org_id = org.get("uuid")
        if not org_id:
            continue
        # Infer country from first location
        first_loc = org["locations"][0] if org["locations"] else {}
        pais = _pais(first_loc)
        config = json.dumps(_PRESETS.get(pais, _PRESET_ES))
        orgs.append((org_id, org["name"], pais, config))

        for loc in org["locations"]:
            loc_pais = _pais(loc)
            locs.append(
                (
                    loc["uuid"],
                    org_id,
                    loc["name"],
                    loc.get("lat"),
                    loc.get("lon"),
                    loc.get("city"),
                    loc.get("province"),
                    loc_pais,
                    loc.get("region_code"),
                    loc.get("postCode") or loc.get("postal_code"),
                    loc.get("address"),
                    True,
                )
            )
            for z in loc.get("zones", []):
                zonas.append((z["uuid"], loc["uuid"], z["zoneName"], z.get("hidden", False)))

    conn.executemany(
        "INSERT INTO organizaciones VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
        orgs,
    )
    conn.executemany(
        "INSERT INTO ubicaciones (ubicacion_id, org_id, nombre, lat, lon, ciudad, provincia, pais_codigo, region_code, codigo_postal, direccion, activa) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
        locs,
    )
    conn.executemany(
        "INSERT INTO zonas (zona_id, ubicacion_id, nombre, hidden) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
        zonas,
    )
    return {"orgs": len(orgs), "locs": len(locs), "zonas": len(zonas)}


def migrate_zone_types() -> int:
    """Populate zonas.zone_type from todas_las_ubicaciones.json."""
    raw_path = _DATA / "todas_las_ubicaciones.json"
    if not raw_path.exists():
        return 0
    raw = json.loads(raw_path.read_text("utf-8"))
    conn = get_conn()
    rows = []
    for org in raw:
        for loc in org.get("locations", []):
            for z in loc.get("zones", []):
                if z.get("uuid") and "zoneType" in z:
                    rows.append((z["zoneType"], z["uuid"]))
    if rows:
        conn.executemany("UPDATE zonas SET zone_type = ? WHERE zona_id = ?", rows)
    return len(rows)


def seed_geo_snapshots() -> int:
    conn = get_conn()
    geo_path = _DATA / "geo_features.json"
    if not geo_path.exists():
        return 0

    geo = json.loads(geo_path.read_text("utf-8"))
    rows = []
    for loc_uuid, snapshots in geo.items():
        if not _UUID_RE.match(loc_uuid):
            continue  # skip _metadata and other non-UUID keys
        if not isinstance(snapshots, list):
            continue
        for snap in snapshots:
            vigente_desde = snap.get("valid_from")
            vigente_hasta = snap.get("valid_to")
            for key, valor in snap.items():
                if key in ("valid_from", "valid_to"):
                    continue
                # Skip non-scalar values (e.g. catchment_rings GeoJSON geometry)
                if not isinstance(valor, (int, float, type(None))):
                    continue
                rows.append((loc_uuid, key, vigente_desde, valor, vigente_hasta))

    conn.executemany(
        """
        INSERT INTO snapshots_geo
            (ubicacion_id, señal_id, vigente_desde, valor, vigente_hasta)
        VALUES (?,?,?,?,?)
        ON CONFLICT DO NOTHING
        """,
        rows,
    )
    return len(rows)


def seed_feature_registry() -> int:
    """
    Registers all known feature keys with their source and initial status.
    Sources:
      esri          — Geo features (active: already in training pipeline)
      supercalendario — Commercial calendar (active)
      eventos_externos — Event features (Open Holidays + Ticketmaster + TheSportsDB + agenda municipal)
    """
    # Import here to avoid circular deps at module level
    from src.data_processing.geo_enrichment import GEO_FEATURE_COLS
    from src.data_processing.supercalendario import CALENDARIO_FEATURE_COLS

    conn = get_conn()
    entries = []

    for key in GEO_FEATURE_COLS:
        entries.append((key, "esri", "geo", '"all"', None, "incompleto", None, None))

    for key in CALENDARIO_FEATURE_COLS:
        entries.append(
            (key, "supercalendario", "calendario", '"all"', None, "con_cobertura", None, None)
        )

    # Open-Meteo weather — stored in valores_señales, fetched on first training call
    for key, nota in [
        (
            "temp_max",
            "Temperatura máxima diaria (°C). API Open-Meteo archive. Caché en valores_señales.",
        ),
        (
            "temp_min",
            "Temperatura mínima diaria (°C). API Open-Meteo archive. Caché en valores_señales.",
        ),
        (
            "llueve",
            "Precipitación > 0 mm (0/1). API Open-Meteo archive. Caché en valores_señales.",
        ),
    ]:
        entries.append((key, "open_meteo", "clima", '"all"', None, "con_cobertura", None, nota))

    # Port data — Málaga Muelle 1 only (prefetch: src/data_ingestion/diaria/cruceros.py)
    entries.append(
        (
            "n_pasajeros_crucero_dia",
            "cruceros",
            "trafico_externo",
            json.dumps(["5c13b57d-782d-4458-911b-64cd40eebb55"]),  # Miniso España org
            json.dumps(["67034276-0d01-4c90-a363-fa75699a19a4"]),  # Malaga Muelle 1
            "con_cobertura",
            None,
            "Escalas de cruceros en Puerto Málaga. Fuente: puertomalaga.com WP-AJAX. "
            "Prefetch automático en src/data_ingestion/diaria/cruceros.py.",
        )
    )

    conn.executemany(
        """
        INSERT INTO señales
            (señal_id, fuente, categoria, org_applicability, location_applicability,
             status, notas)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (señal_id) DO UPDATE
            SET fuente               = EXCLUDED.fuente,
                categoria            = EXCLUDED.categoria,
                org_applicability    = EXCLUDED.org_applicability,
                location_applicability = EXCLUDED.location_applicability,
                status               = EXCLUDED.status,
                notas                = COALESCE(EXCLUDED.notas, señales.notas)
        """,
        [(e[0], e[1], e[2], e[3], e[4], e[5], e[7]) for e in entries],
    )
    return len(entries)


# ── Users migration ──────────────────────────────────────────────────────────


def seed_usuarios() -> int:
    """Migrate users.json → usuarios (idempotent)."""
    users_file = Path(__file__).parent.parent.parent / "users.json"
    if not users_file.exists():
        return 0
    users = json.loads(users_file.read_text())
    conn = get_conn()
    rows = []
    for username, entry in users.items():
        if isinstance(entry, str):
            entry = {"password": entry, "role": "user"}
        rows.append((username, entry.get("password", ""), entry.get("role", "user")))
    conn.executemany(
        "INSERT INTO usuarios (usuario_id, password_hash, role) VALUES (?,?,?) ON CONFLICT DO NOTHING",
        rows,
    )
    return len(rows)


def seed_conversaciones() -> int:
    """Migrate JSON conversation files → conversaciones + mensajes (idempotent)."""
    conv_root = Path(__file__).parent.parent / "data" / "conversations"
    if not conv_root.exists():
        return 0
    conn = get_conn()
    total = 0
    for user_dir in conv_root.iterdir():
        if not user_dir.is_dir():
            continue
        usuario_id = user_dir.name
        for conv_file in sorted(user_dir.glob("*.json")):
            if conv_file.name == "_index.json":
                continue
            try:
                conv = json.loads(conv_file.read_text("utf-8"))
                conversacion_id = conv.get("id", conv_file.stem)
                title = conv.get("title", "Nueva conversación")
                ubicacion_id = conv.get("location_uuid")
                created = datetime.fromtimestamp(conv.get("created_at", time.time()))
                updated = datetime.fromtimestamp(conv.get("updated_at", time.time()))
                conn.execute(
                    "INSERT INTO conversaciones (conversacion_id, usuario_id, title, ubicacion_id, created_at, updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                    [conversacion_id, usuario_id, title, ubicacion_id, created, updated],
                )
                existing = conn.execute(
                    "SELECT COUNT(*) FROM mensajes WHERE conversacion_id = ?",
                    [conversacion_id],
                ).fetchone()[0]
                if existing == 0:
                    msgs = conv.get("messages", [])
                    if msgs:
                        rows = [
                            (
                                conversacion_id,
                                i,
                                m.get("role", "user"),
                                (
                                    m["content"]
                                    if isinstance(m.get("content"), str)
                                    else json.dumps(m.get("content", ""), ensure_ascii=False)
                                ),
                            )
                            for i, m in enumerate(msgs)
                        ]
                        conn.executemany(
                            "INSERT INTO mensajes (conversacion_id, seq, role, content) VALUES (?,?,?,?)",
                            rows,
                        )
                total += 1
            except Exception:
                pass
    return total


def seed_feature_flags() -> dict:
    """
    Seeds activacion_señales for climate and geo features across all active locations.
    - open_meteo → active  (climate variables always enter the model)
    - esri       → inactive (no temporal signal; excluded globally)
    Idempotent: ON CONFLICT DO UPDATE enforces the target state on every run.
    Returns {'active': n, 'inactive': n}.
    """
    conn = get_conn()

    locs = [
        r[0]
        for r in conn.execute("SELECT ubicacion_id FROM ubicaciones WHERE activa = TRUE").fetchall()
    ]
    if not locs:
        return {"active": 0, "inactive": 0}

    climate_keys = [
        r[0]
        for r in conn.execute("SELECT señal_id FROM señales WHERE fuente = 'open_meteo'").fetchall()
    ]
    geo_keys = [
        r[0] for r in conn.execute("SELECT señal_id FROM señales WHERE fuente = 'esri'").fetchall()
    ]

    sql = """
        INSERT INTO activacion_señales (señal_id, ubicacion_id, status, periodicidad)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (señal_id, ubicacion_id) DO UPDATE
            SET status       = EXCLUDED.status,
                periodicidad = EXCLUDED.periodicidad
    """

    # clima: activas en ML, ingesta diaria
    ev_diaria_keys = [
        "ev_vacaciones_escolares",
        "ev_festivo_regional",
        "ev_rank_deportivo",
        "ev_rank_concierto",
        "ev_rank_festival",
        "ev_rank_municipal",
        "ev_rank_total",
    ]
    # cruceros: contexto, ingesta mensual (calendario portuario)
    crucero_keys = ["n_pasajeros_crucero_dia"]

    active_rows = [(fk, loc, "active", "diaria") for fk in climate_keys for loc in locs]
    inactive_rows = [(fk, loc, "inactive", "trimestral") for fk in geo_keys for loc in locs]
    contexto_diaria_rows = [
        (fk, loc, "contexto", "diaria") for fk in ev_diaria_keys for loc in locs
    ]
    contexto_mensual_rows = [
        (fk, loc, "contexto", "mensual") for fk in crucero_keys for loc in locs
    ]

    for batch in (active_rows, inactive_rows, contexto_diaria_rows, contexto_mensual_rows):
        if batch:
            conn.executemany(sql, batch)

    return {
        "active": len(active_rows),
        "inactive": len(inactive_rows),
        "contexto": len(contexto_diaria_rows) + len(contexto_mensual_rows),
    }


# ── CSV ingestion ─────────────────────────────────────────────────────────────


def ingest_visitas_csv(csv_path: str) -> int:
    """
    Bulk-import an Aitanna session CSV into visitas.
    Skips rows whose ubicacion_id is not in ubicaciones.
    Idempotent via ON CONFLICT DO NOTHING.

    Returns the number of rows inserted.
    """
    csv_path_obj = Path(csv_path).resolve()
    if not csv_path_obj.exists():
        return 0

    conn = get_conn()

    org_map = dict(conn.execute("SELECT ubicacion_id, org_id FROM ubicaciones").fetchall())
    if not org_map:
        return 0

    df = pd.read_csv(csv_path_obj, low_memory=False)

    def _safe_int(v, default: int = 0) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default

    def _safe_float(v, default: float = 0.0) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    rows = []
    for _, row in df.iterrows():
        loc_id = str(row.get("location_id", "")).strip()
        if loc_id not in org_map:
            continue
        rows.append(
            (
                str(row["fecha"])[:10],
                str(row.get("zone_uuid", "")),
                loc_id,
                org_map[loc_id],
                _safe_int(row.get("total_visits")),
                _safe_int(row.get("unique_visitors")),
                _safe_int(row.get("new_visitors")),
                _safe_float(row.get("uv_7d")),
                _safe_float(row.get("uv_28d")),
                _safe_float(row.get("uv_month")),
                _safe_float(row.get("uv_year")),
                _safe_float(row.get("freq_7d")),
                _safe_float(row.get("freq_28d")),
                _safe_float(row.get("freq_month")),
                _safe_float(row.get("freq_year")),
                _safe_float(row.get("dwell_time")),
                str(row.get("dwell_hist") or ""),
                str(row.get("hourly_visits") or ""),
            )
        )

    if rows:
        conn.executemany(
            """
            INSERT INTO visitas
                (fecha, zona_id, ubicacion_id, org_id,
                 total_visits, unique_visitors, new_visitors,
                 uv_7d, uv_28d, uv_month, uv_year,
                 freq_7d, freq_28d, freq_month, freq_year,
                 dwell_time_min, dwell_hist, hourly_visits)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

    return len(rows)


def ingest_all_session_csvs() -> int:
    """Import all dataset_*.csv files found in src/data/ into visitas."""
    total = 0
    for csv_file in sorted(_DATA.glob("dataset_*.csv")):
        n_before = get_conn().execute("SELECT COUNT(*) FROM visitas").fetchone()[0]
        ingest_visitas_csv(str(csv_file))
        n_after = get_conn().execute("SELECT COUNT(*) FROM visitas").fetchone()[0]
        added = n_after - n_before
        print(f"  {csv_file.name}: +{added} rows")
        total += added
    return total


# ── entry point ───────────────────────────────────────────────────────────────


def run_all(verbose: bool = True) -> None:
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log("── ubicaciones + organizaciones + zonas")
    r = seed_ubicaciones()
    log(f'   {r["orgs"]} orgs · {r["locs"]} ubicaciones · {r["zonas"]} zonas')

    log("── zonas: zone_type migration")
    n = migrate_zone_types()
    log(f"   {n} zonas actualizadas con zone_type")

    log("── snapshots_geo (geo_features.json → EAV)")
    n = seed_geo_snapshots()
    log(f"   {n} filas geo")

    log("── señales")
    n = seed_feature_registry()
    log(f"   {n} señales registradas")

    log("── activacion_señales: clima → active · geo → inactive")
    r = seed_feature_flags()
    log(f'   {r["active"]} flags active · {r["inactive"]} flags inactive')

    log("── visitas (dataset_*.csv → PostgreSQL)")
    n = ingest_all_session_csvs()
    log(f"   {n} filas de visitas insertadas")

    log("── usuarios (users.json → PostgreSQL)")
    n = seed_usuarios()
    log(f"   {n} usuarios migrados")

    log("── conversaciones + mensajes (JSON → PostgreSQL)")
    n = seed_conversaciones()
    log(f"   {n} conversaciones migradas")

    log("Done.")


if __name__ == "__main__":
    run_all()
