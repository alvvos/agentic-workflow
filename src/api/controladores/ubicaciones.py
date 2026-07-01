from __future__ import annotations

from src.api.modelos.ubicacion import Ubicacion, UbicacionResumen
from src.db.store import get_conn


def listar_ubicaciones(activas_only: bool = True) -> list[UbicacionResumen]:
    sql = (
        "SELECT location_uuid, nombre, ciudad, pais_codigo, activa "
        "FROM dim_ubicaciones "
        + ("WHERE activa = TRUE " if activas_only else "")
        + "ORDER BY nombre"
    )
    rows = get_conn().execute(sql).fetchall()
    return [
        UbicacionResumen(
            location_uuid=r[0],
            nombre=r[1],
            ciudad=r[2],
            pais_codigo=r[3],
            activa=r[4],
        )
        for r in rows
    ]


def obtener_ubicacion(uuid: str) -> Ubicacion | None:
    row = (
        get_conn()
        .execute(
            "SELECT location_uuid, org_uuid, nombre, lat, lon, "
            "ciudad, provincia, pais_codigo, direccion, activa "
            "FROM dim_ubicaciones WHERE location_uuid = ?",
            [uuid],
        )
        .fetchone()
    )
    if row is None:
        return None
    return Ubicacion(
        location_uuid=row[0],
        org_uuid=row[1],
        nombre=row[2],
        lat=row[3],
        lon=row[4],
        ciudad=row[5],
        provincia=row[6],
        pais_codigo=row[7],
        direccion=row[8],
        activa=row[9],
    )
