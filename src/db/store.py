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
    pool_timeout = float(os.getenv("DB_POOL_TIMEOUT", "30"))
    conninfo = (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"user={os.getenv('DB_USER', 'agentic')} "
        f"password={os.getenv('DB_PASSWORD', '')} "
        f"dbname={os.getenv('DB_NAME', 'agentic')} "
        f"connect_timeout={min(int(pool_timeout), 10)}"
    )
    pool = ConnectionPool(
        conninfo,
        min_size=1,
        max_size=int(os.getenv("DB_POOL_MAX", "10")),
        timeout=pool_timeout,
        reconnect_timeout=pool_timeout,
        open=False,
    )
    pool.open(wait=True, timeout=pool_timeout)
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
        ubicacion_id      TEXT             PRIMARY KEY,
        org_id            TEXT             NOT NULL,
        nombre            TEXT             NOT NULL,
        lat               DOUBLE PRECISION,
        lon               DOUBLE PRECISION,
        ciudad            TEXT,
        provincia         TEXT,
        pais_codigo       TEXT             NOT NULL,
        codigo_region     TEXT,
        codigo_postal     TEXT,
        direccion         TEXT,
        activa            BOOLEAN          DEFAULT TRUE,
        anillos_captacion TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zonas (
        zona_id          TEXT    PRIMARY KEY,
        ubicacion_id     TEXT    NOT NULL,
        nombre           TEXT    NOT NULL,
        oculta           BOOLEAN DEFAULT FALSE,
        tipo_zona        TEXT    DEFAULT '',
        parent_zona_id   TEXT    DEFAULT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visitas (
        fecha                DATE             NOT NULL,
        zona_id              TEXT             NOT NULL,
        ubicacion_id         TEXT             NOT NULL,
        org_id               TEXT             NOT NULL,
        total_visitas        INTEGER,
        visitantes_unicos    INTEGER,
        visitantes_nuevos    INTEGER,
        unicos_7d            DOUBLE PRECISION,
        unicos_28d           DOUBLE PRECISION,
        unicos_mes           DOUBLE PRECISION,
        unicos_anyo          DOUBLE PRECISION,
        frecuencia_7d        DOUBLE PRECISION,
        frecuencia_28d       DOUBLE PRECISION,
        frecuencia_mes       DOUBLE PRECISION,
        frecuencia_anyo      DOUBLE PRECISION,
        tiempo_estancia_min           DOUBLE PRECISION,
        histograma_estancia           TEXT,
        visitas_horarias              TEXT,
        boxplot_estancia              TEXT,
        histograma_frecuencia_7d      TEXT,
        histograma_frecuencia_28d     TEXT,
        histograma_frecuencia_mes     TEXT,
        histograma_frecuencia_anyo    TEXT,
        PRIMARY KEY (fecha, zona_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_visitas_ubicacion_fecha
        ON visitas (ubicacion_id, fecha)
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots_geo (
        ubicacion_id   TEXT             NOT NULL,
        señal_id       TEXT             NOT NULL,
        valor          DOUBLE PRECISION,
        actualizado_en TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ubicacion_id, señal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_geo_ubicacion
        ON snapshots_geo (ubicacion_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS valores_señales (
        fecha         DATE             NOT NULL,
        ubicacion_id  TEXT             NOT NULL,
        señal_id      TEXT             NOT NULL,
        valor         DOUBLE PRECISION,
        ingerido_en   TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (fecha, ubicacion_id, señal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_valores_ubicacion_fecha
        ON valores_señales (ubicacion_id, fecha)
    """,
    """
    CREATE TABLE IF NOT EXISTS señales (
        señal_id                  TEXT PRIMARY KEY,
        fuente                    TEXT NOT NULL,
        categoria                 TEXT,
        aplicabilidad_org         JSONB DEFAULT '"all"'::jsonb,
        aplicabilidad_ubicacion   JSONB,
        status                    TEXT  DEFAULT 'incompleto'
                                      CHECK (status IN ('incompleto', 'con_cobertura')),
        notas                     TEXT,
        registrado_en             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        clave_fuente  TEXT    UNIQUE
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
        rol           TEXT      DEFAULT 'user',
        creado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ultimo_acceso TIMESTAMP
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
        titulo          TEXT      DEFAULT 'Nueva conversación',
        ubicacion_id    TEXT,
        creado_en       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actualizado_en  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_usuario_updated
        ON conversaciones (usuario_id, actualizado_en)
    """,
    """
    CREATE TABLE IF NOT EXISTS mensajes (
        msg_id          UUID      DEFAULT gen_random_uuid() PRIMARY KEY,
        conversacion_id TEXT      NOT NULL,
        orden           INTEGER   NOT NULL,
        rol             TEXT      NOT NULL,
        contenido       TEXT,
        creado_en       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion
        ON mensajes (conversacion_id, orden)
    """,
    # Chatbot response cache with native TTL
    """
    CREATE TABLE IF NOT EXISTS cache_chatbot (
        clave_cache  TEXT      PRIMARY KEY,
        pregunta     TEXT      NOT NULL,
        ubicacion_id TEXT,
        respuesta    TEXT      NOT NULL,
        creado_en    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        aciertos     INTEGER   DEFAULT 0,
        expira_en    TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cache_expires
        ON cache_chatbot (expira_en)
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluaciones_señales (
        id               SERIAL           PRIMARY KEY,
        evaluado_en      TIMESTAMPTZ      DEFAULT NOW(),
        señal_id         TEXT             NOT NULL,
        ubicacion_id     TEXT             NOT NULL,
        indice_split     INT              NOT NULL,
        fecha_eval_ini   DATE             NOT NULL,
        fecha_eval_fin   DATE             NOT NULL,
        n_entrenamiento  INT              NOT NULL,
        n_evaluacion     INT              NOT NULL,
        wmape_baseline   DOUBLE PRECISION NOT NULL,
        wmape_con_feat   DOUBLE PRECISION NOT NULL,
        wmape_delta      DOUBLE PRECISION NOT NULL,
        horizonte        INT              NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_evaluaciones_señal
        ON evaluaciones_señales (señal_id, evaluado_en)
    """,
    """
    CREATE TABLE IF NOT EXISTS activacion_señales (
        señal_id      TEXT             NOT NULL,
        ubicacion_id  TEXT             NOT NULL,
        status        TEXT             NOT NULL DEFAULT 'inactive'
                          CHECK (status IN ('active', 'inactive')),
        wmape_delta   DOUBLE PRECISION,
        evaluado_en   TIMESTAMPTZ      DEFAULT NOW(),
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
        creado_en        TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
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
        creado_en    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (ubicacion_id, fuente)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_config_fuentes_fuente ON config_fuentes (fuente) WHERE activo = TRUE
    """,
    """
    CREATE TABLE IF NOT EXISTS categorias_poi (
        categoria   TEXT PRIMARY KEY,
        label       TEXT NOT NULL,
        icono       VARCHAR(64),
        color       VARCHAR(16),
        color_badge VARCHAR(16)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tipos_zona (
        tipo_zona   TEXT PRIMARY KEY,
        label       TEXT NOT NULL,
        icono       VARCHAR(64),
        color       VARCHAR(16),
        tooltip     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categorias_narrativa (
        clave      TEXT PRIMARY KEY,
        label      TEXT NOT NULL,
        icono      VARCHAR(64),
        orden      INT  DEFAULT 99
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS niveles_alerta (
        clave       TEXT PRIMARY KEY,
        color_texto VARCHAR(16),
        color_fondo VARCHAR(16),
        orden       INT DEFAULT 99
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
        esquema_params  TEXT,
        ejemplo_params  JSONB    DEFAULT '{}'::jsonb,
        config          JSONB    NOT NULL DEFAULT '{}'::jsonb,
        activo          BOOLEAN  NOT NULL DEFAULT TRUE,
        creado_en       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

_VISITAS_COLS = [
    ("total_visitas", "INTEGER"),
    ("visitantes_unicos", "INTEGER"),
    ("visitantes_nuevos", "INTEGER"),
    ("unicos_7d", "DOUBLE PRECISION"),
    ("unicos_28d", "DOUBLE PRECISION"),
    ("unicos_mes", "DOUBLE PRECISION"),
    ("unicos_anyo", "DOUBLE PRECISION"),
    ("frecuencia_7d", "DOUBLE PRECISION"),
    ("frecuencia_28d", "DOUBLE PRECISION"),
    ("frecuencia_mes", "DOUBLE PRECISION"),
    ("frecuencia_anyo", "DOUBLE PRECISION"),
    ("tiempo_estancia_min", "DOUBLE PRECISION"),
    ("histograma_estancia", "TEXT"),
    ("visitas_horarias", "TEXT"),
    ("boxplot_estancia", "TEXT"),
    ("histograma_frecuencia_7d", "TEXT"),
    ("histograma_frecuencia_28d", "TEXT"),
    ("histograma_frecuencia_mes", "TEXT"),
    ("histograma_frecuencia_anyo", "TEXT"),
]


def _apply_ddl(conn: PgConn) -> None:
    # Renames must run before the DDL loop: indexes reference the new Spanish
    # column names and would fail on existing DBs that still have old English names.
    _migrar_renombrar_tablas(conn)
    _migrar_renombrar_columnas(conn)
    _migrar_columnas_espanol(conn)
    for stmt in _DDL:
        conn.execute(stmt.strip())
    _migrar_limpiar_columnas(conn)
    _migrate_zonas(conn)
    _migrate_zone_types_miniso(conn)
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
    _migrate_snapshots_geo_simple(conn)
    _migrate_señales_fill_gaps(conn)
    _purgar_senales_obsoletas(conn)
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
              IF EXISTS (SELECT FROM pg_tables WHERE schemaname='public' AND tablename='{viejo}') THEN
                IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname='public' AND tablename='{nuevo}') THEN
                  -- caso normal: solo existe la vieja → renombrar
                  ALTER TABLE {viejo} RENAME TO {nuevo};
                ELSIF (SELECT COUNT(*) FROM {nuevo}) = 0 THEN
                  -- caso migración: nueva existe vacía (creada por DDL) y vieja tiene datos → swap
                  DROP TABLE {nuevo} CASCADE;
                  ALTER TABLE {viejo} RENAME TO {nuevo};
                END IF;
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
    _rename_col("visitas", "org_uuid", "org_id")
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


def _migrar_columnas_espanol(conn: PgConn) -> None:
    """Normaliza todos los nombres de columna al convenio español. Idempotente."""

    def _r(table: str, old: str, new: str) -> None:
        conn.execute(
            f"""
            DO $$ BEGIN
              IF EXISTS (SELECT FROM information_schema.columns
                         WHERE table_name='{table}' AND column_name='{old}')
              THEN ALTER TABLE {table} RENAME COLUMN {old} TO {new};
              END IF;
            END $$
            """
        )

    _RENAMES = [
        # visitas
        ("visitas", "total_visits", "total_visitas"),
        ("visitas", "unique_visitors", "visitantes_unicos"),
        ("visitas", "new_visitors", "visitantes_nuevos"),
        ("visitas", "uv_7d", "unicos_7d"),
        ("visitas", "uv_28d", "unicos_28d"),
        ("visitas", "uv_month", "unicos_mes"),
        ("visitas", "uv_year", "unicos_anyo"),
        ("visitas", "freq_7d", "frecuencia_7d"),
        ("visitas", "freq_28d", "frecuencia_28d"),
        ("visitas", "freq_month", "frecuencia_mes"),
        ("visitas", "freq_year", "frecuencia_anyo"),
        ("visitas", "dwell_time_min", "tiempo_estancia_min"),
        ("visitas", "dwell_hist", "histograma_estancia"),
        ("visitas", "hourly_visits", "visitas_horarias"),
        # zonas
        ("zonas", "hidden", "oculta"),
        ("zonas", "zone_type", "tipo_zona"),
        # tipos_zona
        ("tipos_zona", "zone_type", "tipo_zona"),
        # eventos
        ("eventos", "source_key", "clave_fuente"),
        # señales
        ("señales", "icon_cls", "icono"),
        ("señales", "agg_fn", "funcion_agregacion"),
        ("señales", "display_mode", "modo_visualizacion"),
        ("señales", "canonical_type", "tipo_canonico"),
        ("señales", "location_applicability", "aplicabilidad_ubicacion"),
        ("señales", "org_applicability", "aplicabilidad_org"),
        # snapshots_geo
        ("snapshots_geo", "ingested_at", "ingerido_en"),
        # valores_señales
        ("valores_señales", "ingested_at", "ingerido_en"),
        # evaluaciones_señales
        ("evaluaciones_señales", "evaluated_at", "evaluado_en"),
        ("evaluaciones_señales", "split_idx", "indice_split"),
        ("evaluaciones_señales", "n_train", "n_entrenamiento"),
        ("evaluaciones_señales", "n_eval", "n_evaluacion"),
        # activacion_señales
        ("activacion_señales", "evaluated_at", "evaluado_en"),
        # usuarios
        ("usuarios", "created_at", "creado_en"),
        ("usuarios", "last_login", "ultimo_acceso"),
        ("usuarios", "role", "rol"),
        # conversaciones
        ("conversaciones", "title", "titulo"),
        ("conversaciones", "created_at", "creado_en"),
        ("conversaciones", "updated_at", "actualizado_en"),
        # mensajes
        ("mensajes", "role", "rol"),
        ("mensajes", "content", "contenido"),
        ("mensajes", "created_at", "creado_en"),
        ("mensajes", "seq", "orden"),
        # cache_chatbot
        ("cache_chatbot", "cache_key", "clave_cache"),
        ("cache_chatbot", "question", "pregunta"),
        ("cache_chatbot", "answer", "respuesta"),
        ("cache_chatbot", "created_at", "creado_en"),
        ("cache_chatbot", "hits", "aciertos"),
        ("cache_chatbot", "expires_at", "expira_en"),
        # puntos_interes
        ("puntos_interes", "created_at", "creado_en"),
        # config_fuentes
        ("config_fuentes", "created_at", "creado_en"),
        # categorias_poi
        ("categorias_poi", "category", "categoria"),
        ("categorias_poi", "icon_cls", "icono"),
        ("categorias_poi", "badge_color", "color_badge"),
        # categorias_narrativa
        ("categorias_narrativa", "category_key", "clave"),
        ("categorias_narrativa", "icon_cls", "icono"),
        ("categorias_narrativa", "sort_order", "orden"),
        # niveles_alerta
        ("niveles_alerta", "level_key", "clave"),
        ("niveles_alerta", "text_color", "color_texto"),
        ("niveles_alerta", "bg_color", "color_fondo"),
        ("niveles_alerta", "sort_order", "orden"),
        # fuentes
        ("fuentes", "created_at", "creado_en"),
        ("fuentes", "params_schema", "esquema_params"),
        ("fuentes", "params_ejemplo", "ejemplo_params"),
        # ubicaciones
        ("ubicaciones", "region_code", "codigo_region"),
        ("ubicaciones", "catchment_rings_json", "anillos_captacion"),
    ]
    for table, old, new in _RENAMES:
        _r(table, old, new)


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
        "INSERT INTO usuarios (usuario_id, password_hash, rol) VALUES (?,?,?)"
        " ON CONFLICT (usuario_id) DO UPDATE SET password_hash = excluded.password_hash, rol = excluded.rol",
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
    """Añade columnas de display a señales y siembra/actualiza metadatos de señales conocidas."""
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS label               TEXT")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS sublabel            TEXT")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS color               VARCHAR(16)")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS icono               VARCHAR(64)")
    conn.execute(
        "ALTER TABLE señales ADD COLUMN IF NOT EXISTS funcion_agregacion  VARCHAR(8) DEFAULT 'sum'"
    )
    conn.execute(
        "ALTER TABLE señales ADD COLUMN IF NOT EXISTS modo_visualizacion  VARCHAR(20) DEFAULT 'yoy'"
    )

    # ── Señales canónicas — un UPSERT unificado ───────────────────────────────
    # Campos: (señal_id, fuente, categoria, modo_visualizacion,
    #          label, sublabel, color, icono, funcion_agregacion, notas)
    _SIGNALS = [
        # turismo · cruceros
        (
            "n_pasajeros_crucero_oficial",
            "puertos_estado",
            "turismo",
            "cruceros",
            "Pasajeros crucero",
            "pax oficiales",
            "#1abc9c",
            "fas fa-ship",
            "sum",
            "Pasajeros oficiales de crucero — Puertos del Estado. Latencia ~25 días. Embarques + desembarques.",
        ),
        (
            "n_pasajeros_crucero_dia",
            "cruceros",
            "turismo",
            "cruceros",
            "Pasajeros crucero día",
            "pax totales",
            "#1abc9c",
            "fas fa-ship",
            "sum",
            "Escalas de crucero scrapeadas de la web del puerto. Latencia 1 día. Fallback del dato oficial durante el período de lag.",
        ),
        # clima · calendario
        (
            "llueve",
            "open_meteo",
            "clima",
            "calendario",
            "Lluvia",
            "días",
            "#3498db",
            "fas fa-cloud-rain",
            "sum",
            "Días con precipitación registrada. Correlaciona negativamente con la afluencia en zonas exteriores.",
        ),
        (
            "temp_max",
            "open_meteo",
            "clima",
            "calendario",
            "Temperatura máx.",
            "°C",
            "#e74c3c",
            "fas fa-thermometer-full",
            "mean",
            "Temperatura máxima diaria en la ubicación (°C). Valores extremos pueden reducir la afluencia.",
        ),
        (
            "temp_min",
            "open_meteo",
            "clima",
            "calendario",
            "Temperatura mín.",
            "°C",
            "#3498db",
            "fas fa-thermometer-empty",
            "mean",
            "Temperatura mínima diaria en la ubicación (°C).",
        ),
    ]
    for sid, fuente, cat, mode, lbl, sub, col, icon, agg, notas in _SIGNALS:
        conn.execute(
            "INSERT INTO señales "
            "  (señal_id, fuente, categoria, status, modo_visualizacion, "
            "   label, sublabel, color, icono, funcion_agregacion, notas) "
            "VALUES (?,?,?,'con_cobertura',?,?,?,?,?,?,?) "
            "ON CONFLICT (señal_id) DO UPDATE SET "
            "  label               = EXCLUDED.label, "
            "  sublabel            = EXCLUDED.sublabel, "
            "  color               = EXCLUDED.color, "
            "  icono               = EXCLUDED.icono, "
            "  funcion_agregacion  = EXCLUDED.funcion_agregacion, "
            "  modo_visualizacion  = EXCLUDED.modo_visualizacion, "
            "  notas               = EXCLUDED.notas",
            [sid, fuente, cat, mode, lbl, sub, col, icon, agg, notas],
        )

    # ── Raw event type rows — also carry tipo_canonico ────────────────────────
    _RAW_EVENTS = [
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
            "  (señal_id, fuente, categoria, status, label, sublabel, color, icono, "
            "   funcion_agregacion, modo_visualizacion, tipo_canonico) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (señal_id) DO UPDATE SET "
            "  tipo_canonico       = EXCLUDED.tipo_canonico, "
            "  label               = EXCLUDED.label, "
            "  sublabel            = EXCLUDED.sublabel, "
            "  color               = EXCLUDED.color, "
            "  icono               = EXCLUDED.icono, "
            "  funcion_agregacion  = EXCLUDED.funcion_agregacion, "
            "  modo_visualizacion  = EXCLUDED.modo_visualizacion",
            list(row),
        )


def _migrate_registries(conn: PgConn) -> None:
    """
    Siembra los registries de display (POI, zonas, narrativa, alertas) y añade
    la columna canonical_type a señales. Todos los inserts son
    ON CONFLICT DO NOTHING salvo los eventos raw, que upsertean el canonical_type
    y campos visuales para mantenerse alineados con cambios futuros.
    """
    # Ensure all columns exist in registry tables (may be absent in older DBs)
    for tbl, col, typ in [
        ("categorias_poi", "icono", "VARCHAR(64)"),
        ("categorias_poi", "color", "VARCHAR(16)"),
        ("categorias_poi", "color_badge", "VARCHAR(16)"),
        ("tipos_zona", "icono", "VARCHAR(64)"),
        ("tipos_zona", "color", "VARCHAR(16)"),
        ("tipos_zona", "tooltip", "TEXT"),
        ("categorias_narrativa", "icono", "VARCHAR(64)"),
        ("categorias_narrativa", "orden", "INT DEFAULT 99"),
        ("niveles_alerta", "color_texto", "VARCHAR(16)"),
        ("niveles_alerta", "color_fondo", "VARCHAR(16)"),
        ("niveles_alerta", "orden", "INT DEFAULT 99"),
    ]:
        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {typ}")

    # ── categorias_poi ────────────────────────────────────────────────────────
    _POI_CATS = [
        ("metro", "Metro / Transporte", "fas fa-subway", "#5E35B1", "primary"),
        ("transporte_bus", "Bus / Parada", "fas fa-bus", "#039BE5", "info"),
        ("tourist_poi", "Polo turístico", "fas fa-landmark", "#F9A825", "warning"),
        ("event_venue", "Sala de eventos", "fas fa-theater-masks", "#00ACC1", "info"),
        ("competitor", "Competidor", "fas fa-store", "#E53935", "danger"),
        ("restauracion", "Restauración", "fas fa-utensils", "#F4511E", "warning"),
        ("ancla", "Tienda ancla / gran superficie", "fas fa-building", "#43A047", "success"),
        ("otro", "Otro", "fas fa-map-pin", "#78909C", "secondary"),
    ]
    conn.executemany(
        "INSERT INTO categorias_poi (categoria, label, icono, color, color_badge) "
        "VALUES (?,?,?,?,?) ON CONFLICT (categoria) DO UPDATE SET "
        "label = EXCLUDED.label, icono = EXCLUDED.icono, "
        "color = EXCLUDED.color, color_badge = EXCLUDED.color_badge",
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
        "INSERT INTO tipos_zona (tipo_zona, label, icono, color, tooltip) "
        "VALUES (?,?,?,?,?) ON CONFLICT (tipo_zona) DO NOTHING",
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
        "INSERT INTO categorias_narrativa (clave, label, icono, orden) "
        "VALUES (?,?,?,?) ON CONFLICT (clave) DO NOTHING",
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
        "INSERT INTO niveles_alerta (clave, color_texto, color_fondo, orden) "
        "VALUES (?,?,?,?) ON CONFLICT (clave) DO NOTHING",
        _ALERT_LEVELS,
    )

    # ── señales.tipo_canonico + fallback_señal_id columns ────────────────────
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS tipo_canonico TEXT")
    conn.execute("ALTER TABLE señales ADD COLUMN IF NOT EXISTS fallback_señal_id TEXT")

    _RAW_EVENTS = [
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
            "(señal_id, fuente, categoria, status, label, sublabel, color, icono, "
            " funcion_agregacion, modo_visualizacion, tipo_canonico) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (señal_id) DO UPDATE SET "
            "tipo_canonico=EXCLUDED.tipo_canonico, label=EXCLUDED.label, "
            "sublabel=EXCLUDED.sublabel, color=EXCLUDED.color, icono=EXCLUDED.icono, "
            "funcion_agregacion=EXCLUDED.funcion_agregacion, modo_visualizacion=EXCLUDED.modo_visualizacion",
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
    conn.execute("ALTER TABLE ubicaciones ADD COLUMN IF NOT EXISTS anillos_captacion TEXT")


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
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS tipo_zona TEXT DEFAULT ''")
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS parent_zona_id TEXT DEFAULT NULL")
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS funnel_step INT DEFAULT NULL")
    # zone_enum: valor "zone" del reporte diario Aitanna (mayor = más exterior).
    # Fuente de verdad estable; no depende de nombres de zona.
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS zone_enum INT DEFAULT NULL")
    # Campos de la API Aitanna: lastZone / isTopParent
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS es_ultima_zona BOOLEAN DEFAULT NULL")
    conn.execute("ALTER TABLE zonas ADD COLUMN IF NOT EXISTS es_top_parent BOOLEAN DEFAULT NULL")


def _migrate_zone_types_miniso(conn: PgConn) -> None:
    """Seedea zone_type y funnel_step para Miniso España.

    funnel_step es el orden explícito en el funnel de conversión (entero, nullable).
    Calle=1 (exterior), Tienda=2 (interior), Caja=3 (checkout).
    Sub-zonas (Planta 0/1, Caja 0/1) quedan con funnel_step=NULL — el funnel las ignora.
    Idempotente: solo actualiza filas con funnel_step NULL.
    """
    _MINISO_ORG = "5c13b57d-782d-4458-911b-64cd40eebb55"
    _FUNNEL_ZONES = [
        ("Calle", "exterior", 1),
        ("Tienda", "interior", 2),
        ("Caja", "checkout", 3),
    ]
    for nombre, tipo, step in _FUNNEL_ZONES:
        conn.execute(
            """
            UPDATE zonas SET tipo_zona = ?, funnel_step = ?
            WHERE nombre = ?
              AND funnel_step IS NULL
              AND (tipo_zona IS NULL OR tipo_zona = '')
              AND ubicacion_id IN (
                  SELECT ubicacion_id FROM ubicaciones WHERE org_id = ?
              )
            """,
            (tipo, step, nombre, _MINISO_ORG),
        )


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
        "esquema_params": None,
        "ejemplo_params": {},
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
        "esquema_params": "{'ajax_url': '<URL del endpoint WordPress AJAX>', 'pais_codigo': 'ES', 'señal_id': 'n_pasajeros_crucero_dia'}",
        "ejemplo_params": {
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
        "fuente": "puertos_estado",
        "periodicidad": "mensual",
        "categoria": "turismo",
        "descripcion": "Pasajeros de crucero oficiales — Puertos del Estado. Total mensual embarcados + desembarcados.",
        "url_referencia": "https://www.puertos.es/en/data/statistics/monthly",
        "cobertura_desde": "2012-01",
        "latencia_dias": 25,
        "paises": ["ES"],
        "esquema_params": "{'port_authority': '<nombre exacto de la Autoridad Portuaria en el XLSX>'}",
        "ejemplo_params": {"port_authority": "Malaga"},
        "config": {
            "feature_key": "n_pasajeros_crucero_oficial",
            "listing_url": "https://www.puertos.es/en/data/statistics/monthly",
            "hoja_excel": "Pasajeros crucero",
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
        "esquema_params": "{'radio_m': 1200, 'max_resultados': 200, 'categorias': {'<esri_category_id>': ['<tipo_interno>', '<label>']}}",
        "ejemplo_params": {"radio_m": 1200},
        "config": {
            "base_url": "https://places-api.arcgis.com/arcgis/rest/services/places-service/v1",
            "radio_m": 1200,
            "page_size": 20,
            "max_category_ids_per_call": 10,
            "categorias": {
                # Transporte público
                "4bf58dd8d48988d1fd931735": ["metro", "Metro Station"],
                "4bf58dd8d48988d129951735": ["metro", "Rail Station"],
                "52f2ab2ebcbc57f1066b8b4f": ["transporte_bus", "Bus Station"],
                # Atracciones turísticas y culturales
                "4bf58dd8d48988d12d941735": ["tourist_poi", "Monument / Landmark"],
                "4deefb944765f83613cdba6e": ["tourist_poi", "Historic Site"],
                "4bf58dd8d48988d181941735": ["tourist_poi", "Museum"],
                "4bf58dd8d48988d137941735": ["event_venue", "Theater"],
                "5032792091d4c4b30a586d5c": ["event_venue", "Concert Hall"],
                # Restauración (atractor de permanencia y flujo recurrente)
                "4d4b7105d754a06374d81259": ["restauracion", "Restaurant"],
                # Competidores directos
                "4bf58dd8d48988d103951735": ["competitor", "Clothing Store"],
                "4bf58dd8d48988d1f6941735": ["competitor", "Department Store"],
                "63be6904847c3692a84b9bec": ["competitor", "Fashion Retail"],
                # Anclas: generadores de tráfico masivo
                "52f2ab2ebcbc57f1066b8b46": ["ancla", "Supermarket"],
                "4bf58dd8d48988d1fd941735": ["ancla", "Shopping Mall"],
                "4bf58dd8d48988d1fa931735": ["ancla", "Hotel"],
            },
            "valores_categoria": {
                "metro": 0.85,
                "transporte_bus": 0.70,
                "tourist_poi": 0.70,
                "event_venue": 0.65,
                "restauracion": 0.60,
                "competitor": 0.80,
                "ancla": 0.80,
                "otro": 0.50,
            },
        },
    },
    {
        "fuente": "google_places",
        "periodicidad": "mensual",
        "categoria": "contexto_espacial",
        "descripcion": "POIs del entorno via Google Maps Places Nearby Search — complementa Esri con mayor cobertura local.",
        "url_referencia": "https://developers.google.com/maps/documentation/places/web-service/search-nearby",
        "cobertura_desde": None,
        "latencia_dias": 0,
        "paises": ["ES", "MX", "PT"],
        "esquema_params": "{'radio_m': 1200, 'max_resultados': 200}",
        "ejemplo_params": {"radio_m": 1200},
        "config": {
            "tipo_conector": "pois_google",
            "radio_m": 1200,
            "max_resultados": 200,
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
                 cobertura_desde, latencia_dias, paises, esquema_params,
                 ejemplo_params, config, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, TRUE)
            ON CONFLICT (fuente) DO UPDATE SET
                periodicidad    = EXCLUDED.periodicidad,
                categoria       = EXCLUDED.categoria,
                descripcion     = EXCLUDED.descripcion,
                url_referencia  = EXCLUDED.url_referencia,
                cobertura_desde = EXCLUDED.cobertura_desde,
                latencia_dias   = EXCLUDED.latencia_dias,
                paises          = EXCLUDED.paises,
                esquema_params  = EXCLUDED.esquema_params,
                ejemplo_params  = EXCLUDED.ejemplo_params,
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
                entry["esquema_params"],
                _json.dumps(entry["ejemplo_params"], ensure_ascii=False),
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
        "cruceros": {"tipo_conector": "agenda_ajax_tabla"},
        "puertos_estado": {"tipo_conector": "excel_mensual", "modo": "listado"},
        "esri_places": {"tipo_conector": "pois_radio"},
        "google_places": {"tipo_conector": "pois_google"},
    }
    for fuente, extra_config in mapeo.items():
        conn.execute(
            "UPDATE fuentes SET config = config || %s::jsonb WHERE fuente = %s",
            [_json.dumps(extra_config), fuente],
        )


def _migrate_snapshots_geo_simple(conn: PgConn) -> None:
    """
    Simplifica snapshots_geo a un modelo plano: una fila por (ubicacion_id, señal_id).
    La cadencia es mensual y borra lo anterior en cada ingesta — sin histórico temporal.
    Si la tabla ya tiene el esquema nuevo (sin vigente_desde), no hace nada.
    """
    cols = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'snapshots_geo'"
        ).fetchall()
    }
    if not cols or "vigente_desde" not in cols:
        return
    conn.execute("DROP TABLE IF EXISTS snapshots_geo CASCADE")
    conn.execute(
        """
        CREATE TABLE snapshots_geo (
            ubicacion_id   TEXT             NOT NULL,
            señal_id       TEXT             NOT NULL,
            valor          DOUBLE PRECISION,
            actualizado_en TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ubicacion_id, señal_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_geo_ubicacion ON snapshots_geo (ubicacion_id)"
    )


def _migrate_señales_fill_gaps(conn: PgConn) -> None:
    """
    Añade fill_gaps a señales: 'zero' para señales de evento puntual
    (cruceros, lluvia) donde la ausencia de dato significa valor=0;
    'ffill' para señales continuas (temperatura) donde interpolar es correcto.

    get_señal_diaria() usa esta columna para rellenar huecos sin inflar sumas.
    """
    conn.execute(
        "ALTER TABLE señales ADD COLUMN IF NOT EXISTS fill_gaps TEXT "
        "CHECK (fill_gaps IN ('zero', 'ffill')) DEFAULT 'zero'"
    )
    # Señales continuas — temperatura: interpolar huecos tiene sentido
    conn.execute(
        "UPDATE señales SET fill_gaps = 'ffill' WHERE señal_id IN ('temp_max', 'temp_min')"
    )
    # Señales de evento puntual — ya tienen DEFAULT 'zero', forzamos explícitamente
    conn.execute(
        "UPDATE señales SET fill_gaps = 'zero' "
        "WHERE señal_id IN ('llueve', 'n_pasajeros_crucero_dia', "
        "                   'n_pasajeros_crucero_oficial', 'escala_crucero')"
    )


def _purgar_senales_obsoletas(conn: PgConn) -> None:
    """
    Elimina de la DB las señales y eventos de fuentes ya eliminadas.
    Idempotente — usa DELETE WHERE ... IN (...) seguro.
    """
    # Desactivar fuentes eliminadas (no DELETE, por si hay referencias históricas)
    _fuentes_obsoletas = [
        "open_holidays",
        "ticketmaster",
        "thesportsdb",
        "agenda_es",
        "newsdata",
        "metro_madrid",
        "ine_eoh",
    ]
    placeholders = ",".join(["%s"] * len(_fuentes_obsoletas))
    conn.execute(
        f"UPDATE fuentes SET activo = FALSE WHERE fuente IN ({placeholders})",
        _fuentes_obsoletas,
    )

    # Señales a eliminar (CASCADE borra valores_señales, activacion_señales, evaluaciones_señales)
    _senales_obsoletas = [
        # eventos / agenda
        "ev_vacaciones_escolares",
        "ev_festivo_regional",
        "ev_rank_deportivo",
        "ev_rank_concierto",
        "ev_rank_festival",
        "ev_rank_municipal",
        "ev_rank_total",
        "n_eventos_gran_via",
        "tm_concierto",
        "tm_festival",
        "tm_deportivo",
        "concierto_wizink",
        "estreno_callao",
        "festival_madrid",
        "manifestacion_gran_via",
        "partido_deportivo",
        "concierto",
        "festival",
        "deportivo",
        "evento_municipal",
        # movilidad
        "afluencia_metro_gran_via",
        "afluencia_metro_callao",
        "afluencia_metro_sol",
        # turismo no-cruceros
        "n_turistas_isocrona",
        "ine_viajeros_hoteleros",
        # calendario escolar
        "cal_escolar_is_break",
        "cal_escolar_dias_hasta",
    ]
    s_placeholders = ",".join(["%s"] * len(_senales_obsoletas))
    conn.execute(
        f"DELETE FROM señales WHERE señal_id IN ({s_placeholders})",
        _senales_obsoletas,
    )

    # Eventos crudos: conservar solo escalas de crucero
    conn.execute("DELETE FROM eventos WHERE evento_key NOT IN ('escala_crucero')")

    # Sync markers de fuentes eliminadas
    _sync_markers = [f"_sync_{f}" for f in _fuentes_obsoletas]
    sm_placeholders = ",".join(["%s"] * len(_sync_markers))
    conn.execute(
        f"DELETE FROM valores_señales WHERE señal_id IN ({sm_placeholders})",
        _sync_markers,
    )

    # config_fuentes para fuentes eliminadas
    conn.execute(
        f"DELETE FROM config_fuentes WHERE fuente IN ({placeholders})",
        _fuentes_obsoletas,
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
