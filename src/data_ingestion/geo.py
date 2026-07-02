"""
Helpers de estado geoespacial — consulta snapshots_geo para el audit mensual.
"""

from __future__ import annotations


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
