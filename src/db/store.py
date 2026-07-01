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
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

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
    CREATE TABLE IF NOT EXISTS organizaciones (
        org_id            TEXT PRIMARY KEY,
        nombre            TEXT NOT NULL,
        pais_codigo       TEXT NOT NULL,
        config_calendario JSONB DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ubicaciones (
        ubicacion_id  TEXT             PRIMARY KEY,
        org_id        TEXT             NOT NULL,
        nombre        TEXT             NOT NULL,
        lat           DOUBLE PRECISION,
        lon           DOUBLE PRECISION,
        ciudad        TEXT,
        provincia     TEXT,
        pais_codigo   TEXT             NOT NULL,
        region_code   TEXT,
        codigo_postal TEXT,
        direccion     TEXT,
        activa        BOOLEAN          DEFAULT TRUE,
        catchment_rings_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zonas (
        zona_id          TEXT    PRIMARY KEY,
        ubicacion_id     TEXT    NOT NULL,
        nombre           TEXT    NOT NULL,
        hidden           BOOLEAN DEFAULT FALSE,
        zone_type        TEXT    DEFAULT '',
        parent_zona_id   TEXT    DEFAULT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visitas (
        fecha             DATE             NOT NULL,
        zona_id           TEXT             NOT NULL,
        ubicacion_id      TEXT             NOT NULL,
        org_id            TEXT             NOT NULL,
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
        PRIMARY KEY (fecha, zona_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_visitas_ubicacion_fecha
        ON visitas (ubicacion_id, fecha)
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots_geo (
        ubicacion_id TEXT             NOT NULL,
        señal_id      TEXT             NOT NULL,
        vigente_desde DATE             NOT NULL,
        valor         DOUBLE PRECISION,
        vigente_hasta DATE,
        ingested_at   TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ubicacion_id, señal_id, vigente_desde)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_geo_ubicacion_fecha
        ON snapshots_geo (ubicacion_id, vigente_desde)
    """,
    """
    CREATE TABLE IF NOT EXISTS valores_señales (
        fecha         DATE             NOT NULL,
        ubicacion_id  TEXT             NOT NULL,
        señal_id      TEXT             NOT NULL,
        valor         DOUBLE PRECISION,
        ingested_at   TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (fecha, ubicacion_id, señal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_valores_ubicacion_fecha
        ON valores_señales (ubicacion_id, fecha)
    """,
    """
    CREATE TABLE IF NOT EXISTS señales (
        señal_id               TEXT PRIMARY KEY,
        fuente                 TEXT NOT NULL,
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
    CREATE TABLE IF NOT EXISTS eventos (
        id            UUID    DEFAULT gen_random_uuid() PRIMARY KEY,
        org_id        TEXT,
        ubicacion_id  TEXT,
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
    CREATE INDEX IF NOT EXISTS idx_eventos_org_fecha
        ON eventos (org_id, fecha_inicio)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_eventos_ubicacion_fecha
        ON eventos (ubicacion_id, fecha_inicio)
    """,
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        usuario_id    TEXT      PRIMARY KEY,
        password_hash TEXT      NOT NULL,
        role          TEXT      DEFAULT 'user',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login    TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accesos_usuario (
        usuario_id TEXT NOT NULL REFERENCES usuarios(usuario_id)        ON DELETE CASCADE,
        org_id     TEXT NOT NULL REFERENCES organizaciones(org_id)      ON DELETE CASCADE,
        PRIMARY KEY (usuario_id, org_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversaciones (
        conversacion_id TEXT      PRIMARY KEY,
        usuario_id      TEXT      NOT NULL,
        title           TEXT      DEFAULT 'Nueva conversación',
        ubicacion_id    TEXT,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_usuario_updated
        ON conversaciones (usuario_id, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS mensajes (
        msg_id          UUID      DEFAULT gen_random_uuid() PRIMARY KEY,
        conversacion_id TEXT      NOT NULL,
        seq             INTEGER   NOT NULL,
        role            TEXT      NOT NULL,
        content         TEXT,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion
        ON mensajes (conversacion_id, seq)
    """,
    # Chatbot response cache with native TTL
    """
    CREATE TABLE IF NOT EXISTS cache_chatbot (
        cache_key    TEXT      PRIMARY KEY,
        question     TEXT      NOT NULL,
        ubicacion_id TEXT,
        answer       TEXT      NOT NULL,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        hits         INTEGER   DEFAULT 0,
        expires_at   TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cache_expires
        ON cache_chatbot (expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluaciones_señales (
        id             SERIAL           PRIMARY KEY,
        evaluated_at   TIMESTAMPTZ      DEFAULT NOW(),
        señal_id       TEXT             NOT NULL,
        ubicacion_id   TEXT             NOT NULL,
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
    CREATE INDEX IF NOT EXISTS idx_evaluaciones_señal
        ON evaluaciones_señales (señal_id, evaluated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS activacion_señales (
        señal_id      TEXT             NOT NULL,
        ubicacion_id  TEXT             NOT NULL,
        status        TEXT             NOT NULL DEFAULT 'inactive'
                          CHECK (status IN ('active', 'inactive')),
        wmape_delta   DOUBLE PRECISION,
        evaluated_at  TIMESTAMPTZ      DEFAULT NOW(),
        PRIMARY KEY (señal_id, ubicacion_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_activacion_señales_ubicacion
        ON activacion_señales (ubicacion_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS puntos_interes (
        id               SERIAL           PRIMARY KEY,
        org_id           TEXT             NOT NULL,
        ubicacion_id     TEXT             NOT NULL,
        nombre           TEXT             NOT NULL,
        lat              DOUBLE PRECISION NOT NULL,
        lon              DOUBLE PRECISION NOT NULL,
        categoria        TEXT             NOT NULL,
        valor_relativo   DOUBLE PRECISION DEFAULT 0.5,
        detalle          TEXT,
        radio_m          INTEGER,
        isocrona_minutos INTEGER,
        isocrona_geojson JSONB,
        fuente           TEXT             DEFAULT 'manual',
        activo           BOOLEAN          DEFAULT TRUE,
        created_at       TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (ubicacion_id, nombre, categoria)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_puntos_interes_ubicacion
        ON puntos_interes (ubicacion_id)
        WHERE activo = TRUE
    """,
    """
    CREATE TABLE IF NOT EXISTS config_fuentes (
        id           SERIAL    PRIMARY KEY,
        ubicacion_id TEXT      NOT NULL,
        fuente       TEXT      NOT NULL,
        params       JSONB     NOT NULL DEFAULT '{}',
        activo       BOOLEAN   NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (ubicacion_id, fuente)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_config_fuentes_fuente ON config_fuentes (fuente) WHERE activo = TRUE
    """,
    """
    CREATE TABLE IF NOT EXISTS categorias_poi (
        category    TEXT PRIMARY KEY,
        label       TEXT NOT NULL,
        icon_cls    VARCHAR(64),
        color       VARCHAR(16),
        badge_color VARCHAR(16)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tipos_zona (
        zone_type   TEXT PRIMARY KEY,
        label       TEXT NOT NULL,
        icon_cls    VARCHAR(64),
        color       VARCHAR(16),
        tooltip     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categorias_narrativa (
        category_key TEXT PRIMARY KEY,
        label        TEXT NOT NULL,
        icon_cls     VARCHAR(64),
        sort_order   INT  DEFAULT 99
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS niveles_alerta (
        level_key  TEXT PRIMARY KEY,
        text_color VARCHAR(16),
        bg_color   VARCHAR(16),
        sort_order INT DEFAULT 99
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fuentes (
        fuente          TEXT PRIMARY KEY,
        periodicidad    TEXT CHECK (periodicidad IN ('diaria', 'mensual', 'semanal')),
        categoria       TEXT,
        descripcion     TEXT,
        url_referencia  TEXT,
        cobertura_desde TEXT,
        latencia_dias   INTEGER,
        paises          JSONB    DEFAULT '[]'::jsonb,
        params_schema   TEXT,
        params_ejemplo  JSONB    DEFAULT '{}'::jsonb,
        config          JSONB    NOT NULL DEFAULT '{}'::jsonb,
        activo          BOOLEAN  NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

_VISITAS_COLS = [
    ("total_visits", "INTEGER"),
    ("unique_visitors", "INTEGER"),
    ("new_visitors", "INTEGER"),
    ("uv_7d", "DOUBLE PRECISION"),
    ("uv_28d", "DOUBLE PRECISION"),
    ("uv_month", "DOUBLE PRECISION"),
    ("uv_year", "DOUBLE PRECISION"),
    ("freq_7d", "DOUBLE PRECISION"),
    ("freq_28d", "DOUBLE PRECISION"),
    ("freq_month", "DOUBLE PRECISION"),
    ("freq_year", "DOUBLE PRECISION"),
    ("dwell_time_min", "DOUBLE PRECISION"),
    ("dwell_hist", "TEXT"),
    ("hourly_visits", "TEXT"),
]


def _apply_ddl(conn: PgConn) -> None:
    for stmt in _DDL:
        conn.execute(stmt.strip())
    _migrar_renombrar_tablas(conn)
    _migrar_renombrar_columnas(conn)
    _migrar_limpiar_columnas(conn)
    _migrate_zonas(conn)
    _migrate_visitas(conn)
    _migrate_ubicaciones(conn)
    _migrate_fk_constraints(conn)
    _migrate_activacion_señales(conn)
    _migrate_señales(conn)
    _migrate_señales_fks(conn)
    _migrate_activacion_señales_contexto(conn)
    _migrate_activacion_señales_periodicidad(conn)
    _migrate_señales_display(conn)
    _migrate_puntos_interes(conn)
    _migrate_config_fuentes(conn)
    _migrate_registries(conn)
    _migrate_fuentes(conn)
    _migrar_tipo_conector(conn)
    _sync_users_from_json(conn)


def _migrar_renombrar_tablas(conn: PgConn) -> None:
    """Renombra las tablas con prefijos ingleses a nombres en español. Idempotente."""
    _renames = [
        # (viejo, nuevo)  — raíz primero, dependientes después
        ("dim_organizaciones", "organizaciones"),
        ("dim_usuarios", "usuarios"),
        ("dim_ubicaciones", "ubicaciones"),
        ("dim_zonas", "zonas"),
        ("fact_visitas", "visitas"),
        ("store_features_ext", "valores_señales"),
        ("feature_registry", "señales"),
        ("feature_flags", "activacion_señales"),
        ("feature_eval_results", "evaluaciones_señales"),
        ("store_geo_snapshots", "snapshots_geo"),
        ("store_calendario_org", "eventos"),
        ("location_pois", "puntos_interes"),
        ("location_source_config", "config_fuentes"),
        ("source_registry", "fuentes"),
        ("user_org_access", "accesos_usuario"),
        ("chat_conversaciones", "conversaciones"),
        ("chat_mensajes", "mensajes"),
        ("cache_responses", "cache_chatbot"),
        ("poi_category_registry", "categorias_poi"),
        ("zone_type_registry", "tipos_zona"),
        ("narrative_category_registry", "categorias_narrativa"),
        ("alert_level_registry", "niveles_alerta"),
    ]
    for viejo, nuevo in _renames:
        conn.execute(
            f"""
            DO $$ BEGIN
              IF EXISTS (SELECT FROM pg_tables WHERE schemaname='public' AND tablename='{viejo}')
                 AND NOT EXISTS (SELECT FROM pg_tables WHERE schemaname='public' AND tablename='{nuevo}')
              THEN ALTER TABLE {viejo} RENAME TO {nuevo};
              END IF;
            END $$
            """
        )
    # Eliminar model_registry si existe
    conn.execute("DROP TABLE IF EXISTS model_registry CASCADE")


def _migrar_renombrar_columnas(conn: PgConn) -> None:
    """Renombra columnas clave en las tablas ya renombradas. Idempotente."""

    def _rename_col(table: str, old_col: str, new_col: str) -> None:
        conn.execute(
            f"""
            DO $$ BEGIN
              IF EXISTS (SELECT FROM information_schema.columns
                         WHERE table_name='{table}' AND column_name='{old_col}')
              THEN ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col};
              END IF;
            END $$
            """
        )

    # org_uuid → org_id
    _rename_col("organizaciones", "org_uuid", "org_id")
    _rename_col("ubicaciones", "org_uuid", "org_id")
    _rename_col("eventos", "org_uuid", "org_id")
    _rename_col("accesos_usuario", "org_uuid", "org_id")

    # location_uuid → ubicacion_id
    _rename_col("ubicaciones", "location_uuid", "ubicacion_id")
    _rename_col("zonas", "location_uuid", "ubicacion_id")
    _rename_col("visitas", "location_uuid", "ubicacion_id")
    _rename_col("valores_señales", "location_uuid", "ubicacion_id")
    _rename_col("snapshots_geo", "location_uuid", "ubicacion_id")
    _rename_col("eventos", "location_uuid", "ubicacion_id")
    _rename_col("puntos_interes", "location_uuid", "ubicacion_id")
    _rename_col("config_fuentes", "location_uuid", "ubicacion_id")
    _rename_col("activacion_señales", "location_uuid", "ubicacion_id")
    _rename_col("evaluaciones_señales", "location_uuid", "ubicacion_id")
    _rename_col("conversaciones", "location_uuid", "ubicacion_id")
    _rename_col("cache_chatbot", "location_uuid", "ubicacion_id")

    # zone_uuid → zona_id
    _rename_col("zonas", "zone_uuid", "zona_id")
    _rename_col("visitas", "zone_uuid", "zona_id")
    _rename_col("zonas", "parent_zone_uuid", "parent_zona_id")

    # user_id → usuario_id
    _rename_col("usuarios", "user_id", "usuario_id")
    _rename_col("accesos_usuario", "user_id", "usuario_id")
    _rename_col("conversaciones", "user_id", "usuario_id")

    # conv_id → conversacion_id
    _rename_col("conversaciones", "conv_id", "conversacion_id")
    _rename_col("mensajes", "conv_id", "conversacion_id")

    # feature_key → señal_id
    _rename_col("señales", "feature_key", "señal_id")
    _rename_col("activacion_señales", "feature_key", "señal_id")
    _rename_col("evaluaciones_señales", "feature_key", "señal_id")
    _rename_col("valores_señales", "feature_key", "señal_id")
    _rename_col("snapshots_geo", "feature_key", "señal_id")

    # value → valor (solo en valores_señales y snapshots_geo)
    _rename_col("valores_señales", "value", "valor")
    _rename_col("snapshots_geo", "value", "valor")

    # source → fuente (solo columna "source" que significa fuente de datos)
    _rename_col("señales", "source", "fuente")
    _rename_col("config_fuentes", "source", "fuente")

    # valid_from / valid_to → vigente_desde / vigente_hasta (en snapshots_geo)
    _rename_col("snapshots_geo", "valid_from", "vigente_desde")
    _rename_col("snapshots_geo", "valid_to", "vigente_hasta")

    # puntos_interes: org_uuid → org_id (ya renombrado como ubicacion_id en la FK col)
    _rename_col("puntos_interes", "org_uuid", "org_id")

    # fallback_feature_key → fallback_señal_id en señales
    _rename_col("señales", "fallback_feature_key", "fallback_señal_id")


def _migrar_limpiar_columnas(conn: PgConn) -> None:
    """Elimina columnas vestigio."""
    conn.execute("ALTER TABLE ubicaciones DROP COLUMN IF EXISTS country_code")
    conn.execute("ALTER TABLE zonas DROP COLUMN IF EXISTS last_zone")
    conn.execute("ALTER TABLE zonas DROP COLUMN IF EXISTS sort_order")
    conn.execute("ALTER TABLE activacion_señales DROP COLUMN IF EXISTS wmape_delta")


def _sync_users_from_json(conn: PgConn) -> None:
    """Upsert users from users.json into usuarios on every startup."""
    import json as _json
    from pathlib import Path as _Path

    users_file = _Path(__file__).parent.parent.parent / "users.json"
    if not users_file.exists():
        return
    users = _json.loads(users_file.read_text())
    rows = []
    for username, entry in users.items():
        if isinstance(entry, str):
            entry = {"password": entry, "role": "user"}
        rows.append((username, entry.get("password", ""), entry.get("role", "user")))
    conn.executemany(
        "INSERT INTO usuarios (usuario_id, password_hash, role) VALUES (?,?,?)"
        " ON CONFLICT (usuario_id) DO UPDATE SET password_hash = excluded.password_hash, role = excluded.role",
        rows,
    )


def _migrate_señales(conn: PgConn) -> None:
    """Elimina wmape_delta de señales, actualiza CHECK de status, añade fill_method."""
    conn.execute("ALTER TABLE señales DROP COLUMN IF EXISTS wmape_delta")
    conn.execute("ALTER TABLE señales DROP COLUMN IF EXISTS fill_method")
    conn.execute("ALTER TABLE señales DROP CONSTRAINT IF EXISTS feature_registry_status_check")
    conn.execute("ALTER TABLE señales DROP CONSTRAINT IF EXISTS señales_status_check")
    # Primero sanear filas con status obsoleto (active/rejected), luego añadir constraint
    conn.execute(
        "UPDATE señales SET status = 'con_cobertura' " "WHERE status IN ('active', 'testing')"
    )
    conn.execute(
        "UPDATE señales SET status = 'incompleto' "
        "WHERE status NOT IN ('incompleto', 'con_cobertura')"
    )
    conn.execute(
        "ALTER TABLE señales ADD CONSTRAINT señales_status_check "
        "CHECK (status IN ('incompleto', 'con_cobertura'))"
    )


def _migrate_activacion_señales_periodicidad(conn: PgConn) -> None:
    """
    Añade columna periodicidad a activacion_señales.

    Valores: 'diaria' | 'mensual' | 'trimestral' | 'puntual' | 'nunca'
    Default 'diaria' — no rompe filas existentes.
    """
    conn.execute(
        "ALTER TABLE activacion_señales ADD COLUMN IF NOT EXISTS periodicidad TEXT "
        "NOT NULL DEFAULT 'diaria'"
    )
    conn.execute("ALTER TABLE activacion_señales DROP CONSTRAINT IF EXISTS ff_periodicidad_check")
    conn.execute(
        "ALTER TABLE activacion_señales ADD CONSTRAINT ff_periodicidad_check "
        "CHECK (periodicidad IN ('diaria', 'mensual', 'trimestral', 'puntual', 'nunca'))"
    )


def _migrate_señales_display(conn: PgConn) -> None:
    """Añade columnas de display a señales y siembra metadatos de señales conocidas."""
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS label        TEXT")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS sublabel     TEXT")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS color        VARCHAR(16)")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS icon_cls     VARCHAR(64)")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS agg_fn " "VARCHAR(8) DEFAULT 'sum'")
    conn.execute(
        "ALTER TABLE señales ADD COLUMN IF NOT EXISTS display_mode " "VARCHAR(20) DEFAULT 'yoy'"
    )

    # ── señales display_mode='yoy' ──────────────────────────────────────
    _YOY_UPDATES = [
        (
            "afluencia_metro_gran_via",
            "Metro Gran Vía",
            "validaciones diarias",
            "#e67e22",
            "fas fa-train-subway",
            "sum",
        ),
        (
            "afluencia_metro_callao",
            "Metro Callao",
            "validaciones diarias",
            "#00539B",
            "fas fa-train-subway",
            "sum",
        ),
        (
            "n_turistas_isocrona",
            "Turistas área",
            "pers. en isócrona",
            "#3498db",
            "fas fa-passport",
            "sum",
        ),
        (
            "n_eventos_gran_via",
            "Eventos Gran Vía",
            "eventos en rango",
            "#9b59b6",
            "fas fa-calendar-check",
            "sum",
        ),
        (
            "ev_rank_concierto",
            "Ranking conciertos",
            "score 0-100",
            "#8e44ad",
            "fas fa-music",
            "max",
        ),
        (
            "ev_rank_deportivo",
            "Ranking deportivo",
            "score 0-100",
            "#e74c3c",
            "fas fa-futbol",
            "max",
        ),
        ("ev_rank_festival", "Ranking festivales", "score 0-100", "#2980b9", "fas fa-star", "max"),
        ("ev_rank_municipal", "Ranking municipal", "score 0-100", "#e67e22", "fas fa-city", "max"),
        ("ev_rank_total", "Ranking total", "score 0-100", "#2c3e50", "fas fa-chart-bar", "max"),
    ]
    for fk, lbl, sub, col, icon, agg in _YOY_UPDATES:
        conn.execute(
            "UPDATE señales SET label=?, sublabel=?, color=?, icon_cls=?, "
            "agg_fn=?, display_mode='yoy' WHERE señal_id=?",
            [lbl, sub, col, icon, agg, fk],
        )

    # ── señales display_mode='cruceros' ─────────────────────────────────
    _CRUCEROS_UPDATES = [
        (
            "n_pasajeros_crucero_oficial",
            "Pasajeros crucero",
            "pax oficiales",
            "#1abc9c",
            "fas fa-ship",
            "sum",
        ),
        (
            "n_pasajeros_crucero_dia",
            "Pasajeros crucero día",
            "pax totales",
            "#1abc9c",
            "fas fa-ship",
            "sum",
        ),
    ]
    for fk, lbl, sub, col, icon, agg in _CRUCEROS_UPDATES:
        conn.execute(
            "UPDATE señales SET label=?, sublabel=?, color=?, icon_cls=?, "
            "agg_fn=?, display_mode='cruceros' WHERE señal_id=?",
            [lbl, sub, col, icon, agg, fk],
        )

    # ── señales display_mode='calendario' ────────────────────────────────
    _CAL_UPDATES = [
        ("llueve", "Lluvia", "días", "#3498db", "fas fa-cloud-rain", "sum"),
        ("temp_max", "Temperatura máx.", "°C", "#e74c3c", "fas fa-thermometer-full", "mean"),
        ("temp_min", "Temperatura mín.", "°C", "#3498db", "fas fa-thermometer-empty", "mean"),
        ("ev_festivo_regional", "Festivo regional", "días", "#27ae60", "fas fa-flag", "sum"),
        (
            "ev_vacaciones_escolares",
            "Vacaciones escolares",
            "días",
            "#8e44ad",
            "fas fa-school",
            "sum",
        ),
        ("cal_escolar_is_break", "Período vacacional", "días", "#8e44ad", "fas fa-school", "sum"),
        (
            "cal_escolar_dias_hasta",
            "Días hasta vacaciones",
            "días (media)",
            "#8e44ad",
            "fas fa-school",
            "mean",
        ),
    ]
    for fk, lbl, sub, col, icon, agg in _CAL_UPDATES:
        conn.execute(
            "UPDATE señales SET label=?, sublabel=?, color=?, icon_cls=?, "
            "agg_fn=?, display_mode='calendario' WHERE señal_id=?",
            [lbl, sub, col, icon, agg, fk],
        )

    # ── eventos canonical tipos — display_mode='events_count' (INSERT) ─
    _EVENTS_COUNT_ROWS = [
        (
            "concierto",
            "calendar",
            "eventos",
            "con_cobertura",
            "Conciertos",
            "eventos por mes",
            "#8e44ad",
            "fas fa-music",
            "sum",
        ),
        (
            "festival",
            "calendar",
            "eventos",
            "con_cobertura",
            "Festivales",
            "eventos por mes",
            "#2980b9",
            "fas fa-star",
            "sum",
        ),
        (
            "deportivo",
            "calendar",
            "eventos",
            "con_cobertura",
            "Deportivo",
            "eventos por mes",
            "#e74c3c",
            "fas fa-futbol",
            "sum",
        ),
        (
            "evento_municipal",
            "calendar",
            "eventos",
            "con_cobertura",
            "Municipal",
            "eventos por mes",
            "#e67e22",
            "fas fa-city",
            "sum",
        ),
    ]
    for fk, src, cat, stat, lbl, sub, col, icon, agg in _EVENTS_COUNT_ROWS:
        conn.execute(
            "INSERT INTO señales "
            "(señal_id, fuente, categoria, status, label, sublabel, color, icon_cls, agg_fn, display_mode) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (señal_id) DO UPDATE SET "
            "label=EXCLUDED.label, sublabel=EXCLUDED.sublabel, color=EXCLUDED.color, "
            "icon_cls=EXCLUDED.icon_cls, agg_fn=EXCLUDED.agg_fn, display_mode=EXCLUDED.display_mode",
            [fk, src, cat, stat, lbl, sub, col, icon, agg, "events_count"],
        )


def _migrate_registries(conn: PgConn) -> None:
    """
    Siembra los registries de display (POI, zonas, narrativa, alertas) y añade
    la columna canonical_type a señales. Todos los inserts son
    ON CONFLICT DO NOTHING salvo los eventos raw, que upsertean el canonical_type
    y campos visuales para mantenerse alineados con cambios futuros.
    """
    # ── categorias_poi ────────────────────────────────────────────────────────
    _POI_CATS = [
        ("metro", "Metro / Transporte", "fas fa-subway", "#0052CC", "primary"),
        ("tourist_poi", "Polo turístico", "fas fa-landmark", "#f39c12", "warning"),
        ("event_venue", "Sala de eventos", "fas fa-theater-masks", "#8e44ad", "info"),
        ("competitor", "Competidor", "fas fa-store", "#DC3545", "danger"),
        ("otro", "Otro", "fas fa-map-pin", "#6c757d", "secondary"),
    ]
    conn.executemany(
        "INSERT INTO categorias_poi (category, label, icon_cls, color, badge_color) "
        "VALUES (?,?,?,?,?) ON CONFLICT (category) DO NOTHING",
        _POI_CATS,
    )

    # ── tipos_zona ───────────────────────────────────────────────────────────
    _ZONE_TYPES = [
        (
            "caja",
            "Cierre de venta",
            "fas fa-cash-register",
            "#8e44ad",
            "Zona orientada al cierre de venta.",
        ),
        (
            "tienda",
            "Conversión",
            "fas fa-store",
            "#e67e22",
            "Zona de conversión: entrada a tienda.",
        ),
        (
            "exterior",
            "Captación",
            "fas fa-person-walking",
            "#2980b9",
            "Zona exterior: captación de tráfico.",
        ),
        ("default", "Analítica", "fas fa-layer-group", "#0052CC", None),
    ]
    conn.executemany(
        "INSERT INTO tipos_zona (zone_type, label, icon_cls, color, tooltip) "
        "VALUES (?,?,?,?,?) ON CONFLICT (zone_type) DO NOTHING",
        _ZONE_TYPES,
    )

    # ── categorias_narrativa ──────────────────────────────────────────────────
    _NARRATIVE_CATS = [
        ("trafico", "Tráfico", "fas fa-chart-line", 1),
        ("experiencia", "Experiencia", "fas fa-star", 2),
        ("clima", "Clima", "fas fa-cloud-sun", 3),
        ("eventos", "Eventos", "fas fa-calendar-star", 4),
        ("integridad", "Integridad", "fas fa-shield-check", 5),
    ]
    conn.executemany(
        "INSERT INTO categorias_narrativa (category_key, label, icon_cls, sort_order) "
        "VALUES (?,?,?,?) ON CONFLICT (category_key) DO NOTHING",
        _NARRATIVE_CATS,
    )

    # ── niveles_alerta ─────────────────────────────────────────────────────────
    _ALERT_LEVELS = [
        ("success", "#155724", "#d4edda", 1),
        ("danger", "#721c24", "#f8d7da", 2),
        ("warning", "#856404", "#fff3cd", 3),
        ("primary", "#004085", "#cce5ff", 4),
        ("secondary", "#383d41", "#e2e3e5", 5),
        ("info", "#0c5460", "#d1ecf1", 6),
    ]
    conn.executemany(
        "INSERT INTO niveles_alerta (level_key, text_color, bg_color, sort_order) "
        "VALUES (?,?,?,?) ON CONFLICT (level_key) DO NOTHING",
        _ALERT_LEVELS,
    )

    # ── señales.canonical_type + fallback_señal_id columns ────────────────────
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS canonical_type TEXT")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS fallback_señal_id TEXT")

    _RAW_EVENTS = [
        (
            "tm_concierto",
            "ticketmaster",
            "eventos",
            "con_cobertura",
            "Concierto",
            None,
            "#8e44ad",
            "fas fa-music",
            "sum",
            "raw",
            "concierto",
        ),
        (
            "tm_festival",
            "ticketmaster",
            "eventos",
            "con_cobertura",
            "Festival",
            None,
            "#2980b9",
            "fas fa-star",
            "sum",
            "raw",
            "festival",
        ),
        (
            "tm_deportivo",
            "ticketmaster",
            "eventos",
            "con_cobertura",
            "Deportivo",
            None,
            "#e74c3c",
            "fas fa-futbol",
            "sum",
            "raw",
            "deportivo",
        ),
        (
            "concierto_wizink",
            "manual",
            "eventos",
            "con_cobertura",
            "Concierto",
            None,
            "#8e44ad",
            "fas fa-music",
            "sum",
            "raw",
            "concierto",
        ),
        (
            "estreno_callao",
            "manual",
            "eventos",
            "con_cobertura",
            "Estreno",
            None,
            "#e67e22",
            "fas fa-film",
            "sum",
            "raw",
            "concierto",
        ),
        (
            "festival_madrid",
            "manual",
            "eventos",
            "con_cobertura",
            "Festival",
            None,
            "#2980b9",
            "fas fa-city",
            "sum",
            "raw",
            "festival",
        ),
        (
            "manifestacion_gran_via",
            "manual",
            "eventos",
            "con_cobertura",
            "Marcha",
            None,
            "#c0392b",
            "fas fa-bullhorn",
            "sum",
            "raw",
            "evento_municipal",
        ),
        (
            "partido_deportivo",
            "manual",
            "eventos",
            "con_cobertura",
            "Deportivo",
            None,
            "#e74c3c",
            "fas fa-futbol",
            "sum",
            "raw",
            "deportivo",
        ),
        (
            "escala_crucero",
            "puertos_estado",
            "cruceros",
            "con_cobertura",
            "Crucero",
            None,
            "#16a085",
            "fas fa-ship",
            "sum",
            "raw",
            None,
        ),
    ]
    for row in _RAW_EVENTS:
        conn.execute(
            "INSERT INTO señales "
            "(señal_id, fuente, categoria, status, label, sublabel, color, icon_cls, "
            " agg_fn, display_mode, canonical_type) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (señal_id) DO UPDATE SET "
            "canonical_type=EXCLUDED.canonical_type, label=EXCLUDED.label, "
            "sublabel=EXCLUDED.sublabel, color=EXCLUDED.color, icon_cls=EXCLUDED.icon_cls, "
            "agg_fn=EXCLUDED.agg_fn, display_mode=EXCLUDED.display_mode",
            list(row),
        )


def _migrate_activacion_señales_contexto(conn: PgConn) -> None:
    """
    Añade 'contexto' al CHECK de activacion_señales.status.

    'active'   → entra al modelo ML
    'contexto' → señal de contexto — visible en panel, nunca entra al modelo
    'inactive' → oculto
    """
    conn.execute(
        "ALTER TABLE activacion_señales DROP CONSTRAINT IF EXISTS feature_flags_status_check"
    )
    conn.execute(
        "ALTER TABLE activacion_señales DROP CONSTRAINT IF EXISTS activacion_señales_status_check"
    )
    conn.execute(
        "ALTER TABLE activacion_señales ADD CONSTRAINT activacion_señales_status_check "
        "CHECK (status IN ('active', 'contexto', 'inactive'))"
    )


def _migrate_activacion_señales(conn: PgConn) -> None:
    """Elimina zona_id de activacion_señales si aún existe (versión anterior del esquema)."""
    has_col = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='activacion_señales' AND column_name='zona_id'"
    ).fetchone()
    if not has_col:
        # También chequear el nombre antiguo zone_uuid por si la migración de renombrado aún no corrió
        has_col = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='activacion_señales' AND column_name='zone_uuid'"
        ).fetchone()
    if has_col:
        conn.execute("ALTER TABLE activacion_señales DROP COLUMN IF EXISTS zona_id")
        conn.execute("ALTER TABLE activacion_señales DROP COLUMN IF EXISTS zone_uuid")
        conn.execute("ALTER TABLE activacion_señales DROP CONSTRAINT IF EXISTS uq_feature_flags")
        conn.execute("ALTER TABLE activacion_señales ADD PRIMARY KEY (señal_id, ubicacion_id)")


def _migrate_ubicaciones(conn: PgConn) -> None:
    conn.execute("ALTER TABLE ubicaciones ADD COLUMN IF NOT EXISTS catchment_rings_json TEXT")


def _migrate_fk_constraints(conn: PgConn) -> None:
    """Añade FK ON DELETE CASCADE/SET NULL donde no existan. NOT VALID evita escanear filas existentes."""
    # (table, constraint_name, fk_col, ref_table, ref_col, on_delete_action)
    fks = [
        # jerarquía principal
        ("ubicaciones", "fk_ubi_org", "org_id", "organizaciones", "org_id", "CASCADE"),
        (
            "zonas",
            "fk_zonas_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
        (
            "zonas",
            "fk_zona_parent",
            "parent_zona_id",
            "zonas",
            "zona_id",
            "SET NULL",
        ),
        # datos de visitas y señales
        (
            "visitas",
            "fk_visitas_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
        (
            "snapshots_geo",
            "fk_geo_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
        (
            "valores_señales",
            "fk_valores_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
        # eventos (nullable: solo afecta filas con valor)
        (
            "eventos",
            "fk_eventos_org",
            "org_id",
            "organizaciones",
            "org_id",
            "CASCADE",
        ),
        (
            "eventos",
            "fk_eventos_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
        # chatbot
        (
            "conversaciones",
            "fk_conv_usuario",
            "usuario_id",
            "usuarios",
            "usuario_id",
            "CASCADE",
        ),
        (
            "conversaciones",
            "fk_conv_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
        (
            "mensajes",
            "fk_mensajes_conv",
            "conversacion_id",
            "conversaciones",
            "conversacion_id",
            "CASCADE",
        ),
        # caché de respuestas (nullable)
        (
            "cache_chatbot",
            "fk_cache_loc",
            "ubicacion_id",
            "ubicaciones",
            "ubicacion_id",
            "CASCADE",
        ),
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


def _migrate_señales_fks(conn: PgConn) -> None:
    """señales es la fuente de verdad: borrar una señal la elimina de todas las tablas."""
    fks = [
        (
            "activacion_señales",
            "fk_activacion_señales",
            "señal_id",
            "señales",
            "señal_id",
        ),
        (
            "evaluaciones_señales",
            "fk_eval_señales",
            "señal_id",
            "señales",
            "señal_id",
        ),
        (
            "valores_señales",
            "fk_valores_señales",
            "señal_id",
            "señales",
            "señal_id",
        ),
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


def _migrate_zonas(conn: PgConn) -> None:
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS zone_type TEXT DEFAULT ''")
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS parent_zona_id TEXT DEFAULT NULL")


def _migrate_config_fuentes(conn: PgConn) -> None:
    """Siembra config por defecto para ubicaciones conocidas."""
    import json as _json

    _GV_UUID = "251e7f40-95c7-4678-aa48-df1b90e3461c"
    _MALAGA_UUID = "67034276-0d01-4c90-a363-fa75699a19a4"

    _ROWS = [
        (
            _GV_UUID,
            "esri_places",
            _json.dumps({"radio_m": 1200, "max_resultados": 200}),
        ),
        (
            _GV_UUID,
            "metro_madrid",
            _json.dumps(
                {
                    "estaciones": [
                        {"nombre": "Gran Vía", "slug": "gran_via"},
                        {"nombre": "Callao", "slug": "callao"},
                        {"nombre": "Sol", "slug": "sol"},
                    ],
                    "anyo_url": "https://www.metromadrid.es/export/sites/metro/comun/documentos/viajeros/Estadistica_{year}.xlsx",
                }
            ),
        ),
        (
            _GV_UUID,
            "ine_eoh",
            _json.dumps({"provincia_nombre": "Madrid", "tabla_viajeros": 2078}),
        ),
        (
            _MALAGA_UUID,
            "cruceros",
            _json.dumps(
                {
                    "ajax_url": "https://www.puertomalaga.com/wp-admin/admin-ajax.php",
                    "pais_codigo": "ES",
                }
            ),
        ),
    ]
    conn.executemany(
        "INSERT INTO config_fuentes (ubicacion_id, fuente, params) VALUES (?,?,?) "
        "ON CONFLICT (ubicacion_id, fuente) DO NOTHING",
        _ROWS,
    )


def _migrate_puntos_interes(conn: PgConn) -> None:
    """Siembra los POIs de Gran Vía si la tabla está vacía para esa ubicación."""
    _GV_UUID = "251e7f40-95c7-4678-aa48-df1b90e3461c"
    already = conn.execute(
        "SELECT 1 FROM puntos_interes WHERE ubicacion_id = ? LIMIT 1", [_GV_UUID]
    ).fetchone()
    if already:
        return
    org_row = conn.execute(
        "SELECT org_id FROM ubicaciones WHERE ubicacion_id = ?", [_GV_UUID]
    ).fetchone()
    if not org_row:
        return
    org_id = org_row[0]
    _SEED = [
        (
            _GV_UUID,
            org_id,
            "Gran Vía · L1 / L5",
            40.4193,
            -3.7014,
            "metro",
            1.0,
            "~32 000 validaciones/día · 3 min a pie",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Callao · L3 / L5",
            40.4207,
            -3.7077,
            "metro",
            0.75,
            "~24 000 validaciones/día · 5 min a pie",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Sol · L1 / L2 / L3",
            40.4168,
            -3.7026,
            "metro",
            0.95,
            "~60 000 validaciones/día · nodo central · 8 min a pie",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Santo Domingo · L2",
            40.4194,
            -3.7110,
            "metro",
            0.35,
            "~8 000 validaciones/día · 7 min a pie",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Puerta del Sol",
            40.4168,
            -3.7038,
            "tourist_poi",
            1.0,
            "~25 000 turistas/día · km 0 de España",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Plaza Mayor",
            40.4155,
            -3.7074,
            "tourist_poi",
            0.9,
            "~18 000 visitas/día · epicentro turístico",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Mercado de San Miguel",
            40.4152,
            -3.7088,
            "tourist_poi",
            0.55,
            "~7 000 visitas/día · mercado gastronómico",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Teatro Real",
            40.4231,
            -3.7086,
            "event_venue",
            0.8,
            "Ópera y conciertos · hasta 1 746 asientos",
            None,
            None,
        ),
        (
            _GV_UUID,
            org_id,
            "Cines Callao",
            40.4217,
            -3.7059,
            "event_venue",
            0.6,
            "Estrenos y premieres · Plaza de Callao",
            None,
            None,
        ),
    ]
    conn.executemany(
        "INSERT INTO puntos_interes "
        "(ubicacion_id, org_id, nombre, lat, lon, categoria, valor_relativo, detalle, "
        " radio_m, isocrona_minutos) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (ubicacion_id, nombre, categoria) DO NOTHING",
        _SEED,
    )


_SOURCE_REGISTRY_SEED = [
    # ── Diarias universales ───────────────────────────────────────────────────
    {
        "fuente": "weather",
        "periodicidad": "diaria",
        "categoria": "meteorologia",
        "descripcion": "Datos meteorológicos históricos y previsión (Open-Meteo).",
        "url_referencia": "https://open-meteo.com/",
        "cobertura_desde": "2024-01-01",
        "latencia_dias": 1,
        "paises": [],
        "params_schema": None,
        "params_ejemplo": {},
        "config": {},
    },
    {
        "fuente": "open_holidays",
        "periodicidad": "diaria",
        "categoria": "eventos",
        "descripcion": "Festivos nacionales y regionales + vacaciones escolares (OpenHolidays API).",
        "url_referencia": "https://www.openholidaysapi.org/",
        "cobertura_desde": "2024-01-01",
        "latencia_dias": 0,
        "paises": [],
        "params_schema": None,
        "params_ejemplo": {},
        "config": {},
    },
    {
        "fuente": "ticketmaster",
        "periodicidad": "diaria",
        "categoria": "eventos",
        "descripcion": "Eventos de conciertos, festivales y deportes (Ticketmaster Discovery API).",
        "url_referencia": "https://developer.ticketmaster.com/",
        "cobertura_desde": "2024-01-01",
        "latencia_dias": 0,
        "paises": [],
        "params_schema": None,
        "params_ejemplo": {},
        "config": {},
    },
    {
        "fuente": "thesportsdb",
        "periodicidad": "diaria",
        "categoria": "eventos",
        "descripcion": "Partidos deportivos por ciudad (TheSportsDB API).",
        "url_referencia": "https://www.thesportsdb.com/",
        "cobertura_desde": "2024-01-01",
        "latencia_dias": 0,
        "paises": [],
        "params_schema": None,
        "params_ejemplo": {},
        "config": {},
    },
    {
        "fuente": "agenda_es",
        "periodicidad": "diaria",
        "categoria": "eventos",
        "descripcion": "Agenda cultural y eventos municipales.",
        "url_referencia": None,
        "cobertura_desde": "2024-01-01",
        "latencia_dias": 0,
        "paises": ["ES"],
        "params_schema": None,
        "params_ejemplo": {},
        "config": {},
    },
    # ── Diarias configuradas ──────────────────────────────────────────────────
    {
        "fuente": "cruceros",
        "periodicidad": "diaria",
        "categoria": "turismo",
        "descripcion": "Escalas de cruceros por puerto (scraping de webs de autoridades portuarias).",
        "url_referencia": None,
        "cobertura_desde": "2024-01-01",
        "latencia_dias": 1,
        "paises": ["ES"],
        "params_schema": "{'ajax_url': '<URL del endpoint WordPress AJAX>', 'pais_codigo': 'ES', 'señal_id': 'n_pasajeros_crucero_dia'}",
        "params_ejemplo": {
            "ajax_url": "https://www.puertomalaga.com/wp-admin/admin-ajax.php",
            "pais_codigo": "ES",
            "señal_id": "n_pasajeros_crucero_dia",
        },
        "config": {
            "feature_key": "n_pasajeros_crucero_dia",
            "categoria_evento": "escala_crucero",
            "action": "get_prevision_turistas_by_date",
        },
    },
    # ── Mensuales ─────────────────────────────────────────────────────────────
    {
        "fuente": "metro_madrid",
        "periodicidad": "mensual",
        "categoria": "movilidad",
        "descripcion": "Validaciones mensuales por estación de metro (Metro de Madrid / CRTM). Proxy del volumen de peatones en la isócrona de la ubicación.",
        "url_referencia": "https://www.metromadrid.es/en/metro-de-madrid/statistics",
        "cobertura_desde": "2016-01",
        "latencia_dias": 45,
        "paises": ["ES"],
        "params_schema": "{'estaciones': [{'nombre': '<nombre exacto en el Excel de Metro Madrid>', 'slug': '<snake_case>'}], 'anyo_url': '<URL pattern con {year}>', 'feature_key_prefix': 'afluencia_metro_'}",
        "params_ejemplo": {
            "estaciones": [
                {"nombre": "Gran Via", "slug": "gran_via"},
                {"nombre": "Callao", "slug": "callao"},
            ],
            "anyo_url": "https://www.metromadrid.es/...",
        },
        "config": {
            "feature_key_prefix": "afluencia_metro_",
        },
    },
    {
        "fuente": "puertos_estado",
        "periodicidad": "mensual",
        "categoria": "turismo",
        "descripcion": "Pasajeros de crucero oficiales — Puertos del Estado. Total mensual embarcados + desembarcados.",
        "url_referencia": "https://www.puertos.es/en/data/statistics/monthly",
        "cobertura_desde": "2012-01",
        "latencia_dias": 25,
        "paises": ["ES"],
        "params_schema": "{'port_authority': '<nombre exacto de la Autoridad Portuaria en el XLSX>'}",
        "params_ejemplo": {"port_authority": "Malaga"},
        "config": {
            "feature_key": "n_pasajeros_crucero_oficial",
            "listing_url": "https://www.puertos.es/en/data/statistics/monthly",
            "hoja_excel": "Pasajeros crucero",
        },
    },
    {
        "fuente": "ine_eoh",
        "periodicidad": "mensual",
        "categoria": "turismo",
        "descripcion": "Viajeros y pernoctaciones en establecimientos hoteleros — INE Encuesta de Ocupación Hotelera.",
        "url_referencia": "https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736177015",
        "cobertura_desde": "1999-01",
        "latencia_dias": 45,
        "paises": ["ES"],
        "params_schema": "{'provincia_nombre': '<fragmento del nombre de provincia en series INE>'}",
        "params_ejemplo": {"provincia_nombre": "Malaga"},
        "config": {
            "base_url": "https://servicios.ine.es/wstempus/js/ES",
            "tabla_viajeros": 2078,
            "feature_key_viajeros": "ine_viajeros_hoteleros",
            "feature_key_pernoctaciones": "ine_pernoctaciones_hoteleras",
        },
    },
    {
        "fuente": "esri_places",
        "periodicidad": "mensual",
        "categoria": "contexto_espacial",
        "descripcion": "POIs del entorno (metro, monumentos, salas de eventos, competidores) — ArcGIS Places API de Esri.",
        "url_referencia": "https://developers.arcgis.com/rest/places/places-service/near-point/",
        "cobertura_desde": None,
        "latencia_dias": 0,
        "paises": ["ES", "MX", "PT"],
        "params_schema": "{'radio_m': 1200, 'max_resultados': 200, 'categorias': {'<esri_category_id>': ['<tipo_interno>', '<label>']}}",
        "params_ejemplo": {"radio_m": 1200},
        "config": {
            "base_url": "https://places-api.arcgis.com/arcgis/rest/services/places-service/v1",
            "radio_m": 1200,
            "page_size": 20,
            "max_category_ids_per_call": 10,
            "categorias": {
                "4bf58dd8d48988d1fd931735": ["metro", "Metro Station"],
                "4bf58dd8d48988d129951735": ["metro", "Rail Station"],
                "4bf58dd8d48988d12d941735": ["tourist_poi", "Monument / Landmark"],
                "4deefb944765f83613cdba6e": ["tourist_poi", "Historic Site"],
                "4bf58dd8d48988d181941735": ["tourist_poi", "Museum"],
                "4bf58dd8d48988d137941735": ["event_venue", "Theater"],
                "5032792091d4c4b30a586d5c": ["event_venue", "Concert Hall"],
                "4bf58dd8d48988d103951735": ["competitor", "Clothing Store"],
                "4bf58dd8d48988d1f6941735": ["competitor", "Department Store"],
                "63be6904847c3692a84b9bec": ["competitor", "Fashion Retail"],
            },
            "valores_categoria": {
                "metro": 0.85,
                "tourist_poi": 0.70,
                "event_venue": 0.65,
                "competitor": 0.80,
                "otro": 0.50,
            },
        },
    },
]


def _migrate_fuentes(conn: PgConn) -> None:
    """
    Puebla/actualiza fuentes con los defaults operacionales de cada fuente.
    Idempotente: usa ON CONFLICT (fuente) DO UPDATE SET para re-aplicar en cada startup.
    """
    import json as _json

    for entry in _SOURCE_REGISTRY_SEED:
        conn.execute(
            """
            INSERT INTO fuentes
                (fuente, periodicidad, categoria, descripcion, url_referencia,
                 cobertura_desde, latencia_dias, paises, params_schema,
                 params_ejemplo, config, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, TRUE)
            ON CONFLICT (fuente) DO UPDATE SET
                periodicidad    = EXCLUDED.periodicidad,
                categoria       = EXCLUDED.categoria,
                descripcion     = EXCLUDED.descripcion,
                url_referencia  = EXCLUDED.url_referencia,
                cobertura_desde = EXCLUDED.cobertura_desde,
                latencia_dias   = EXCLUDED.latencia_dias,
                paises          = EXCLUDED.paises,
                params_schema   = EXCLUDED.params_schema,
                params_ejemplo  = EXCLUDED.params_ejemplo,
                config          = EXCLUDED.config
            """,
            [
                entry["fuente"],
                entry["periodicidad"],
                entry["categoria"],
                entry["descripcion"],
                entry["url_referencia"],
                entry["cobertura_desde"],
                entry["latencia_dias"],
                _json.dumps(entry["paises"], ensure_ascii=False),
                entry["params_schema"],
                _json.dumps(entry["params_ejemplo"], ensure_ascii=False),
                _json.dumps(entry["config"], ensure_ascii=False),
            ],
        )


def _migrar_tipo_conector(conn: PgConn) -> None:
    """
    Añade tipo_conector (y modulo/modo donde aplique) al campo config de cada fuente.
    Idempotente: usa jsonb merge (||) — si el campo ya existe, lo sobreescribe con el mismo valor.
    """
    import json as _json

    mapeo = {
        "weather": {"tipo_conector": "meteorologia"},
        "open_holidays": {"tipo_conector": "festivos_calendario"},
        "ticketmaster": {"tipo_conector": "eventos_api", "modulo": "ticketmaster"},
        "thesportsdb": {"tipo_conector": "eventos_api", "modulo": "thesportsdb"},
        "agenda_es": {"tipo_conector": "eventos_api", "modulo": "agenda_es"},
        "cruceros": {"tipo_conector": "agenda_ajax_tabla"},
        "metro_madrid": {"tipo_conector": "excel_mensual", "modo": "url"},
        "puertos_estado": {"tipo_conector": "excel_mensual", "modo": "listado"},
        "ine_eoh": {"tipo_conector": "series_estadisticas"},
        "esri_places": {"tipo_conector": "pois_radio"},
    }
    for fuente, extra_config in mapeo.items():
        conn.execute(
            "UPDATE fuentes SET config = config || %s::jsonb WHERE fuente = %s",
            [_json.dumps(extra_config), fuente],
        )


def _migrate_visitas(conn: PgConn) -> None:
    # Check both old and new table name
    for tname in ("visitas", "fact_visitas"):
        existing = {
            r[0]
            for r in conn.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{tname}'"
            ).fetchall()
        }
        if existing:
            for col, dtype in _VISITAS_COLS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE {tname} ADD COLUMN IF NOT EXISTS {col} {dtype}")
            break
