"""
Helpers geoespaciales: auditoría de snapshots e ingesta de datos Esri GeoEnrichment.
"""

from __future__ import annotations

import logging

log = logging.getLogger("geo")


def listar_estado(verbose: bool = True) -> list[dict]:
    """
    Devuelve una lista de dicts por ubicacion activa:
      ubicacion_id, nombre, tiene_datos (bool), n_snapshots (int)
    """
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute(
            """
        SELECT u.ubicacion_id, u.nombre,
               COUNT(s.ubicacion_id) AS n_snapshots
          FROM ubicaciones u
          LEFT JOIN snapshots_geo s ON s.ubicacion_id = u.ubicacion_id
         WHERE u.activa = TRUE
         GROUP BY u.ubicacion_id, u.nombre
         ORDER BY u.nombre
        """
        )
        .fetchall()
    )

    estado = []
    for ubicacion_id, nombre, n in rows:
        entry = {
            "ubicacion_id": ubicacion_id,
            "nombre": nombre,
            "tiene_datos": n > 0,
            "n_snapshots": n,
        }
        if verbose:
            mark = "✓" if n > 0 else "✗"
            print(f"  {mark} {nombre} ({n} snapshot(s))")
        estado.append(entry)

    return estado


def ingestar_snapshot_esri(
    ubicacion_id: str,
    valores: dict[str, float | None],
    fecha_entrega: str | None = None,
) -> dict:
    """
    Persiste un snapshot de GeoEnrichment en snapshots_geo con política temporal.

    Primera entrega (sin snapshot previo):
      Crea un único snapshot [2024-01-01 → open] backdatado al inicio del histórico.

    Actualizaciones posteriores:
      Cierra el snapshot vigente (vigente_hasta = fecha_entrega - 1 día) y crea
      un nuevo snapshot [fecha_entrega → open] con los valores actualizados.

    Devuelve {"primera_entrega": bool, "n_features": int}.
    """
    from datetime import date, timedelta

    from src.db.store import get_conn

    conn = get_conn()
    hoy = str(date.today())
    fecha = fecha_entrega or hoy

    existing = conn.execute(
        """
        SELECT vigente_desde FROM snapshots_geo
        WHERE ubicacion_id = ? AND vigente_hasta IS NULL
        LIMIT 1
        """,
        [ubicacion_id],
    ).fetchone()

    primera_entrega = existing is None

    if not primera_entrega:
        ayer = str(date.fromisoformat(fecha) - timedelta(days=1))
        conn.execute(
            """
            UPDATE snapshots_geo SET vigente_hasta = ?
            WHERE ubicacion_id = ? AND vigente_hasta IS NULL
            """,
            [ayer, ubicacion_id],
        )

    vigente_desde = "2024-01-01" if primera_entrega else fecha

    filas = [
        (ubicacion_id, señal_id, vigente_desde, valor)
        for señal_id, valor in valores.items()
        if valor is not None
    ]

    conn.executemany(
        """
        INSERT INTO snapshots_geo (ubicacion_id, señal_id, vigente_desde, valor)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (ubicacion_id, señal_id, vigente_desde) DO UPDATE SET
            valor = excluded.valor,
            ingested_at = CURRENT_TIMESTAMP
        """,
        filas,
    )

    log.info(
        "[%s] geo snapshot %s — %d features (primera_entrega=%s)",
        ubicacion_id,
        vigente_desde,
        len(filas),
        primera_entrega,
    )
    return {"primera_entrega": primera_entrega, "n_features": len(filas)}
