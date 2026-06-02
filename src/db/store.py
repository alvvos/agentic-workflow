"""
PostgreSQL store — ThreadedConnectionPool via psycopg2.

Provides PgConn, a DuckDB-compatible wrapper so existing callers
(queries.py, seed.py, auth.py, chatbot/tools.py) need zero changes.

Connection config via .env:
    DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME / DB_POOL_MAX

Usage
-----
  from src.db.store import get_conn
  conn = get_conn()                  # thread-local, autocommit=True
  conn = get_conn(read_only=False)   # read_only ignored (pool is shared)
"""
import os
import threading
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

# ── Connection pool ────────────────────────────────────────────────────────────

_POOL: Optional[ThreadedConnectionPool] = None
_POOL_LOCK = threading.Lock()
_local = threading.local()

_DDL_APPLIED = False
_DDL_LOCK = threading.Lock()


def _build_pool() -> ThreadedConnectionPool:
    return ThreadedConnectionPool(
        minconn=1,
        maxconn=int(os.getenv("DB_POOL_MAX", "10")),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "agentic"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "agentic"),
        connect_timeout=10,
    )


def _pool() -> ThreadedConnectionPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = _build_pool()
    return _POOL


# ── DuckDB-compatible result wrapper ───────────────────────────────────────────

class _PgResult:
    """Wraps a psycopg2 cursor to expose fetchone / fetchall / df."""

    __slots__ = ("_cur",)

    def __init__(self, cur: psycopg2.extensions.cursor):
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


# ── DuckDB-compatible connection wrapper ───────────────────────────────────────

def _duck_to_pg(sql: str) -> str:
    """Convert DuckDB ? positional placeholders to psycopg2 %s.

    Safe because all ? in this codebase are parameter placeholders,
    never literal question marks inside string literals.
    Note: if you add SQL with literal % (e.g. LIKE '%foo%'), escape as %%.
    """
    return sql.replace("?", "%s")


class PgConn:
    """
    Thread-local PostgreSQL connection with a DuckDB-compatible surface.

    execute()     → returns _PgResult with .fetchone() / .fetchall() / .df()
    executemany() → batched INSERT/UPDATE via psycopg2.extras.execute_batch
    """

    __slots__ = ("_conn", "_cur")

    def __init__(self, raw: psycopg2.extensions.connection):
        self._conn = raw
        self._cur: psycopg2.extensions.cursor = raw.cursor()

    def execute(self, sql: str, params=None) -> _PgResult:
        self._cur.execute(_duck_to_pg(sql), params)
        return _PgResult(self._cur)

    def executemany(self, sql: str, params_list) -> None:
        if not params_list:
            return
        psycopg2.extras.execute_batch(
            self._cur, _duck_to_pg(sql), params_list, page_size=500
        )

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


# ── DDL — identical schema to the DuckDB version, types adapted ───────────────

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
        zone_uuid     TEXT    PRIMARY KEY,
        location_uuid TEXT    NOT NULL,
        nombre        TEXT    NOT NULL,
        hidden        BOOLEAN DEFAULT FALSE,
        zone_type     TEXT    DEFAULT ''
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
        status                 TEXT  DEFAULT 'testing',
        wmape_delta            DOUBLE PRECISION,
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


def _migrate_dim_ubicaciones(conn: PgConn) -> None:
    conn.execute(
        "ALTER TABLE dim_ubicaciones ADD COLUMN IF NOT EXISTS catchment_rings_json TEXT"
    )


def _migrate_dim_zonas(conn: PgConn) -> None:
    conn.execute(
        "ALTER TABLE dim_zonas ADD COLUMN IF NOT EXISTS zone_type TEXT DEFAULT ''"
    )


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
