"""
PostgreSQL store — ConnectionPool via psycopg (v3).

Connection config via .env:
    DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME / DB_POOL_MAX

Usage
-----
  from src.db.store import get_conn
  conn = get_conn()                  # thread-local, autocommit=True
  conn = get_conn(read_only=False)   # read_only ignored (pool is shared)
"""
import atexit
import os
import threading
from typing import Optional

import pandas as pd
import psycopg
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

# ── Connection pool ────────────────────────────────────────────────────────────

_POOL: Optional[ConnectionPool] = None
_POOL_LOCK = threading.Lock()
_local = threading.local()

_DDL_APPLIED = False
_DDL_LOCK = threading.Lock()


def _build_pool() -> ConnectionPool:
    conninfo = (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"user={os.getenv('DB_USER', 'agentic')} "
        f"password={os.getenv('DB_PASSWORD', '')} "
        f"dbname={os.getenv('DB_NAME', 'agentic')} "
        f"connect_timeout=10"
    )
    pool = ConnectionPool(
        conninfo,
        min_size=1,
        max_size=int(os.getenv("DB_POOL_MAX", "10")),
        open=False,
    )
    pool.open()
    atexit.register(pool.close)
    return pool


def _pool() -> ConnectionPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = _build_pool()
    return _POOL


# ── Query result wrapper ──────────────────────────────────────────────────────

class _PgResult:
    """Wraps a psycopg cursor to expose fetchone / fetchall / df."""

    __slots__ = ("_cur",)

    def __init__(self, cur: psycopg.Cursor):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def df(self) -> pd.DataFrame:
        if self._cur.description is None:
            return pd.DataFrame()
        cols = [d[0] for d in self._cur.description]
        return pd.DataFrame(self._cur.fetchall(), columns=cols)


# ── Connection wrapper ────────────────────────────────────────────────────────

def _norm_sql(sql: str) -> str:
    """Convert ? positional placeholders to psycopg %s.

    Note: if you add SQL with literal % (e.g. LIKE '%foo%'), escape as %%.
    """
    return sql.replace("?", "%s")


class PgConn:
    """
    Thread-local PostgreSQL connection.

    execute()     → returns _PgResult with .fetchone() / .fetchall() / .df()
    executemany() → batched INSERT/UPDATE via psycopg cursor.executemany
    """

    __slots__ = ("_conn", "_cur")

    def __init__(self, raw: psycopg.Connection):
        self._conn = raw
        self._cur: psycopg.Cursor = raw.cursor()

    def execute(self, sql: str, params=None) -> _PgResult:
        self._cur.execute(_norm_sql(sql), params)
        return _PgResult(self._cur)

    def executemany(self, sql: str, params_list) -> None:
        if not params_list:
            return
        self._cur.executemany(_norm_sql(sql), params_list)

    def close(self) -> None:
        try:
            self._cur.close()
        except Exception:
            pass
        try:
            _pool().putconn(self._conn)
        except Exception:
            pass


# ── Public API ─────────────────────────────────────────────────────────────────

def get_conn(read_only: bool = False) -> PgConn:  # noqa: ARG001  (read_only kept for API compat)
    """
    Returns a thread-local PgConn with autocommit=True.
    Reconnects automatically if the underlying connection was closed.
    Applies the full DDL once per process on first call.
    """
    global _DDL_APPLIED

    conn_obj: Optional[PgConn] = getattr(_local, "conn", None)
    if conn_obj is None or conn_obj._conn.closed:
        # Devolver la conexión cerrada al pool ANTES de pedir una nueva.
        # Sin esto, cada reconexión (ej. idle timeout de Postgres) pierde
        # un slot del pool y eventualmente lo agota (PoolTimeout → 504).
        if conn_obj is not None:
            try:
                _pool().putconn(conn_obj._conn)
            except Exception:
                pass
            _local.conn = None
        raw = _pool().getconn()
        raw.autocommit = True
        conn_obj = PgConn(raw)
        _local.conn = conn_obj

    if not _DDL_APPLIED:
        with _DDL_LOCK:
            if not _DDL_APPLIED:
                _apply_ddl(conn_obj)
                _DDL_APPLIED = True

    return conn_obj


def close_conn() -> None:
    conn_obj: Optional[PgConn] = getattr(_local, "conn", None)
    if conn_obj is not None:
        conn_obj.close()
        try:
            del _local.conn
        except AttributeError:
            pass


# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS dim_organizaciones (
        org_uuid          TEXT PRIMARY KEY,
        nombre            TEXT NOT NULL,
        pais_codigo       TEXT NOT NULL,
        config_calendario JSONB DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_ubicaciones (
        location_uuid TEXT             PRIMARY KEY,
        org_uuid      TEXT             NOT NULL,
        nombre        TEXT             NOT NULL,
        lat           DOUBLE PRECISION,
        lon           DOUBLE PRECISION,
        ciudad        TEXT,
        provincia     TEXT,
        pais_codigo   TEXT             NOT NULL,
        region_code   TEXT,
        country_code  TEXT,
        codigo_postal TEXT,
        direccion     TEXT,
        activa        BOOLEAN          DEFAULT TRUE,
        catchment_rings_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_zonas (
        zone_uuid        TEXT    PRIMARY KEY,
        location_uuid    TEXT    NOT NULL,
        nombre           TEXT    NOT NULL,
        hidden           BOOLEAN DEFAULT FALSE,
        zone_type        TEXT    DEFAULT '',
        parent_zone_uuid TEXT    DEFAULT NULL,
        sort_order       INT     DEFAULT 0,
        last_zone        BOOLEAN DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_visitas (
        fecha             DATE             NOT NULL,
        zone_uuid         TEXT             NOT NULL,
        location_uuid     TEXT             NOT NULL,
        org_uuid          TEXT             NOT NULL,
        total_visits      INTEGER,
        unique_visitors   INTEGER,
        new_visitors      INTEGER,
        uv_7d             DOUBLE PRECISION,
        uv_28d            DOUBLE PRECISION,
        uv_month          DOUBLE PRECISION,
        uv_year           DOUBLE PRECISION,
        freq_7d           DOUBLE PRECISION,
        freq_28d          DOUBLE PRECISION,
        freq_month        DOUBLE PRECISION,
        freq_year         DOUBLE PRECISION,
        dwell_time_min    DOUBLE PRECISION,
        dwell_hist        TEXT,
        hourly_visits     TEXT,
        PRIMARY KEY (fecha, zone_uuid)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fact_loc_fecha
        ON fact_visitas (location_uuid, fecha)
    """,
    """
    CREATE TABLE IF NOT EXISTS store_geo_snapshots (
        location_uuid TEXT             NOT NULL,
        feature_key   TEXT             NOT NULL,
        valid_from    DATE             NOT NULL,
        value         DOUBLE PRECISION,
        valid_to      DATE,
        ingested_at   TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (location_uuid, feature_key, valid_from)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_geo_loc_fecha
        ON store_geo_snapshots (location_uuid, valid_from)
    """,
    """
    CREATE TABLE IF NOT EXISTS store_features_ext (
        fecha         DATE             NOT NULL,
        location_uuid TEXT             NOT NULL,
        feature_key   TEXT             NOT NULL,
        value         DOUBLE PRECISION,
        ingested_at   TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (fecha, location_uuid, feature_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_feat_ext_loc_fecha
        ON store_features_ext (location_uuid, fecha)
    """,
    """
    CREATE TABLE IF NOT EXISTS feature_registry (
        feature_key            TEXT PRIMARY KEY,
        source                 TEXT NOT NULL,
        categoria              TEXT,
        org_applicability      JSONB DEFAULT '"all"'::jsonb,
        location_applicability JSONB,
        status                 TEXT  DEFAULT 'incompleto'
                                   CHECK (status IN ('incompleto', 'con_cobertura')),
        notas                  TEXT,
        registrado_en          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS store_calendario_org (
        id            UUID    DEFAULT gen_random_uuid() PRIMARY KEY,
        org_uuid      TEXT,
        location_uuid TEXT,
        pais_codigo   TEXT,
        evento_key    TEXT    NOT NULL,
        fecha_inicio  DATE    NOT NULL,
        fecha_fin     DATE    NOT NULL,
        metadata      JSONB   DEFAULT '{}'::jsonb,
        fuente        TEXT    DEFAULT 'manual',
        source_key    TEXT    UNIQUE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cal_org_fecha
        ON store_calendario_org (org_uuid, fecha_inicio)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cal_loc_fecha
        ON store_calendario_org (location_uuid, fecha_inicio)
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_usuarios (
        user_id       TEXT      PRIMARY KEY,
        password_hash TEXT      NOT NULL,
        role          TEXT      DEFAULT 'user',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login    TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_org_access (
        user_id  TEXT NOT NULL REFERENCES dim_usuarios(user_id)        ON DELETE CASCADE,
        org_uuid TEXT NOT NULL REFERENCES dim_organizaciones(org_uuid) ON DELETE CASCADE,
        PRIMARY KEY (user_id, org_uuid)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_conversaciones (
        conv_id       TEXT      PRIMARY KEY,
        user_id       TEXT      NOT NULL,
        title         TEXT      DEFAULT 'Nueva conversación',
        location_uuid TEXT,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_user_updated
        ON chat_conversaciones (user_id, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_mensajes (
        msg_id     UUID      DEFAULT gen_random_uuid() PRIMARY KEY,
        conv_id    TEXT      NOT NULL,
        seq        INTEGER   NOT NULL,
        role       TEXT      NOT NULL,
        content    TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_msgs_conv
        ON chat_mensajes (conv_id, seq)
    """,
    """
    CREATE TABLE IF NOT EXISTS model_registry (
        model_id      TEXT      PRIMARY KEY,
        location_uuid TEXT      NOT NULL,
        zone_uuid     TEXT      NOT NULL,
        trained_at    TIMESTAMP,
        features      JSONB,
        metrics       JSONB,
        model_path    TEXT,
        is_valid      BOOLEAN   DEFAULT TRUE
    )
    """,
    # Chatbot response cache with native TTL
    """
    CREATE TABLE IF NOT EXISTS cache_responses (
        cache_key     TEXT      PRIMARY KEY,
        question      TEXT      NOT NULL,
        location_uuid TEXT,
        answer        TEXT      NOT NULL,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        hits          INTEGER   DEFAULT 0,
        expires_at    TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cache_expires
        ON cache_responses (expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS feature_eval_results (
        id             SERIAL           PRIMARY KEY,
        evaluated_at   TIMESTAMPTZ      DEFAULT NOW(),
        feature_key    TEXT             NOT NULL,
        location_uuid  TEXT             NOT NULL,
        split_idx      INT              NOT NULL,
        fecha_eval_ini DATE             NOT NULL,
        fecha_eval_fin DATE             NOT NULL,
        n_train        INT              NOT NULL,
        n_eval         INT              NOT NULL,
        wmape_baseline DOUBLE PRECISION NOT NULL,
        wmape_con_feat DOUBLE PRECISION NOT NULL,
        wmape_delta    DOUBLE PRECISION NOT NULL,
        horizonte      INT              NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_eval_results_feature
        ON feature_eval_results (feature_key, evaluated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS feature_flags (
        feature_key   TEXT             NOT NULL,
        location_uuid TEXT             NOT NULL,
        status        TEXT             NOT NULL DEFAULT 'inactive'
                          CHECK (status IN ('active', 'inactive')),
        wmape_delta   DOUBLE PRECISION,
        evaluated_at  TIMESTAMPTZ      DEFAULT NOW(),
        PRIMARY KEY (feature_key, location_uuid)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_feature_flags_loc
        ON feature_flags (location_uuid)
    """,
]

_FACT_VISITAS_COLS = [
    ("total_visits",    "INTEGER"),
    ("unique_visitors", "INTEGER"),
    ("new_visitors",    "INTEGER"),
    ("uv_7d",           "DOUBLE PRECISION"),
    ("uv_28d",          "DOUBLE PRECISION"),
    ("uv_month",        "DOUBLE PRECISION"),
    ("uv_year",         "DOUBLE PRECISION"),
    ("freq_7d",         "DOUBLE PRECISION"),
    ("freq_28d",        "DOUBLE PRECISION"),
    ("freq_month",      "DOUBLE PRECISION"),
    ("freq_year",       "DOUBLE PRECISION"),
    ("dwell_time_min",  "DOUBLE PRECISION"),
    ("dwell_hist",      "TEXT"),
    ("hourly_visits",   "TEXT"),
]


def _apply_ddl(conn: PgConn) -> None:
    for stmt in _DDL:
        conn.execute(stmt.strip())
    _migrate_dim_zonas(conn)
    _migrate_fact_visitas(conn)
    _migrate_dim_ubicaciones(conn)
    _migrate_fk_constraints(conn)
    _migrate_feature_flags(conn)
    _migrate_feature_registry(conn)
    _migrate_feature_registry_fks(conn)
    _migrate_feature_flags_contexto(conn)
    _sync_users_from_json(conn)


def _sync_users_from_json(conn: PgConn) -> None:
    """Upsert users from users.json into dim_usuarios on every startup."""
    import json as _json
    from pathlib import Path as _Path
    users_file = _Path(__file__).parent.parent.parent / 'users.json'
    if not users_file.exists():
        return
    users = _json.loads(users_file.read_text())
    rows = []
    for username, entry in users.items():
        if isinstance(entry, str):
            entry = {'password': entry, 'role': 'user'}
        rows.append((username, entry.get('password', ''), entry.get('role', 'user')))
    conn.executemany(
        "INSERT INTO dim_usuarios (user_id, password_hash, role) VALUES (?,?,?)"
        " ON CONFLICT (user_id) DO UPDATE SET password_hash = excluded.password_hash, role = excluded.role",
        rows,
    )


def _migrate_feature_registry(conn: PgConn) -> None:
    """Elimina wmape_delta de feature_registry, actualiza CHECK de status, añade fill_method."""
    conn.execute("ALTER TABLE feature_registry DROP COLUMN IF EXISTS wmape_delta")
    conn.execute("ALTER TABLE feature_registry DROP COLUMN IF EXISTS fill_method")
    conn.execute("ALTER TABLE feature_registry DROP CONSTRAINT IF EXISTS feature_registry_status_check")
    # Primero sanear filas con status obsoleto (active/rejected), luego añadir constraint
    conn.execute(
        "UPDATE feature_registry SET status = 'con_cobertura' "
        "WHERE status IN ('active', 'testing')"
    )
    conn.execute(
        "UPDATE feature_registry SET status = 'incompleto' "
        "WHERE status NOT IN ('incompleto', 'con_cobertura')"
    )
    conn.execute(
        "ALTER TABLE feature_registry ADD CONSTRAINT feature_registry_status_check "
        "CHECK (status IN ('incompleto', 'con_cobertura'))"
    )


def _migrate_feature_flags_contexto(conn: PgConn) -> None:
    """
    Añade 'contexto' al CHECK de feature_flags.status y purga ev_* de la BD.

    'active'   → entra al modelo ML y se muestra en panel
    'contexto' → sólo panel (señal de contexto), nunca entra al modelo
    'inactive' → oculto

    ev_* se eliminan completamente: eran features de ML de baja calidad generadas
    por el prefetch (Ticketmaster, TheSportsDB, Open Holidays, agenda municipal).
    """
    conn.execute("ALTER TABLE feature_flags DROP CONSTRAINT IF EXISTS feature_flags_status_check")
    conn.execute(
        "ALTER TABLE feature_flags ADD CONSTRAINT feature_flags_status_check "
        "CHECK (status IN ('active', 'contexto', 'inactive'))"
    )
    ev_keys = [
        'ev_vacaciones_escolares', 'ev_festivo_regional',
        'ev_rank_deportivo', 'ev_rank_concierto',
        'ev_rank_festival', 'ev_rank_municipal', 'ev_rank_total',
    ]
    ph = ','.join(['?' for _ in ev_keys])
    conn.execute(f"DELETE FROM store_features_ext WHERE feature_key IN ({ph})", ev_keys)
    conn.execute(f"DELETE FROM feature_flags     WHERE feature_key IN ({ph})", ev_keys)
    conn.execute(f"DELETE FROM feature_registry  WHERE feature_key IN ({ph})", ev_keys)


def _migrate_feature_flags(conn: PgConn) -> None:
    """Elimina zone_uuid de feature_flags si aún existe (versión anterior del esquema)."""
    has_col = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='feature_flags' AND column_name='zone_uuid'"
    ).fetchone()
    if has_col:
        conn.execute("ALTER TABLE feature_flags DROP COLUMN IF EXISTS zone_uuid")
        conn.execute("ALTER TABLE feature_flags DROP CONSTRAINT IF EXISTS uq_feature_flags")
        conn.execute(
            "ALTER TABLE feature_flags ADD PRIMARY KEY (feature_key, location_uuid)"
        )


def _migrate_dim_ubicaciones(conn: PgConn) -> None:
    conn.execute(
        "ALTER TABLE dim_ubicaciones ADD COLUMN IF NOT EXISTS catchment_rings_json TEXT"
    )


def _migrate_fk_constraints(conn: PgConn) -> None:
    """Añade FK ON DELETE CASCADE/SET NULL donde no existan. NOT VALID evita escanear filas existentes."""
    # (table, constraint_name, fk_col, ref_table, ref_col, on_delete_action)
    fks = [
        # jerarquía principal
        ("dim_ubicaciones",    "fk_ubi_org",       "org_uuid",         "dim_organizaciones", "org_uuid",   "CASCADE"),
        ("dim_zonas",          "fk_zonas_loc",     "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        ("dim_zonas",          "fk_zona_parent",   "parent_zone_uuid", "dim_zonas",          "zone_uuid",  "SET NULL"),
        # datos de visitas y features
        ("fact_visitas",       "fk_fact_loc",      "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        ("store_geo_snapshots","fk_geo_loc",       "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        ("store_features_ext", "fk_feat_ext_loc",  "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        # calendario (nullable: solo afecta filas con valor)
        ("store_calendario_org","fk_cal_org",      "org_uuid",         "dim_organizaciones", "org_uuid",   "CASCADE"),
        ("store_calendario_org","fk_cal_loc",      "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        # modelos ML
        ("model_registry",     "fk_model_loc",     "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        ("model_registry",     "fk_model_zone",    "zone_uuid",        "dim_zonas",          "zone_uuid",  "CASCADE"),
        # chatbot
        ("chat_conversaciones","fk_conv_user",     "user_id",          "dim_usuarios",       "user_id",    "CASCADE"),
        ("chat_conversaciones","fk_conv_loc",      "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
        ("chat_mensajes",      "fk_mensajes_conv", "conv_id",          "chat_conversaciones","conv_id",    "CASCADE"),
        # caché de respuestas (nullable)
        ("cache_responses",    "fk_cache_loc",     "location_uuid",    "dim_ubicaciones",    "location_uuid","CASCADE"),
    ]
    for table, cname, fk_col, ref_table, ref_col, action in fks:
        exists = conn.execute(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = ? AND table_name = ?",
            [cname, table],
        ).fetchone()
        if not exists:
            conn.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {cname} "
                f"FOREIGN KEY ({fk_col}) REFERENCES {ref_table}({ref_col}) "
                f"ON DELETE {action} NOT VALID"
            )


def _migrate_feature_registry_fks(conn: PgConn) -> None:
    """feature_registry es la fuente de verdad: borrar una feature la elimina de todas las tablas."""
    fks = [
        ("feature_flags",        "fk_flags_registry",    "feature_key", "feature_registry", "feature_key"),
        ("feature_eval_results", "fk_eval_registry",     "feature_key", "feature_registry", "feature_key"),
        ("store_features_ext",   "fk_feat_ext_registry", "feature_key", "feature_registry", "feature_key"),
    ]
    for table, cname, fk_col, ref_table, ref_col in fks:
        exists = conn.execute(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = ? AND table_name = ?",
            [cname, table],
        ).fetchone()
        if not exists:
            conn.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {cname} "
                f"FOREIGN KEY ({fk_col}) REFERENCES {ref_table}({ref_col}) "
                f"ON DELETE CASCADE NOT VALID"
            )


def _migrate_dim_zonas(conn: PgConn) -> None:
    conn.execute("ALTER TABLE dim_zonas ADD COLUMN IF NOT EXISTS zone_type TEXT DEFAULT ''")
    conn.execute("ALTER TABLE dim_zonas ADD COLUMN IF NOT EXISTS parent_zone_uuid TEXT DEFAULT NULL")
    conn.execute("ALTER TABLE dim_zonas ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0")
    conn.execute("ALTER TABLE dim_zonas ADD COLUMN IF NOT EXISTS last_zone BOOLEAN DEFAULT FALSE")


def _migrate_fact_visitas(conn: PgConn) -> None:
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'fact_visitas'"
        ).fetchall()
    }
    for col, dtype in _FACT_VISITAS_COLS:
        if col not in existing:
            conn.execute(
                f"ALTER TABLE fact_visitas ADD COLUMN IF NOT EXISTS {col} {dtype}"
            )
