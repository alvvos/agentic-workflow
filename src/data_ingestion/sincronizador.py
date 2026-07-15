import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")

log = logging.getLogger("sincronizador")


def _get_location_ids(ubicaciones_seleccionadas=None):
    try:
        from src.db.queries import get_locations_with_coords

        uuids = get_locations_with_coords()
        if uuids:
            return uuids
    except Exception:
        pass
    return []


def peticion_dia(loc_id, fecha_str):
    url = f"https://platform.aitanna.ai/api/v1/internal/get-anonymous-report/location/{loc_id}/date/{fecha_str}"
    headers = {"x-api-key": AITANNA_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return fecha_str, res.json(), "OK"
        elif res.status_code == 404:
            return fecha_str, None, "404"
        else:
            return fecha_str, None, f"Error {res.status_code}"
    except Exception as e:
        return fecha_str, None, f"Exception: {str(e)}"


def _upsert_visitas(rows: list) -> None:
    from src.db.store import get_conn

    if not rows:
        return
    get_conn().executemany(
        """
        INSERT INTO visitas
            (fecha, zona_id, ubicacion_id, org_id,
             total_visitas, visitantes_unicos, visitantes_nuevos,
             unicos_7d, unicos_28d, unicos_mes, unicos_anyo,
             frecuencia_7d, frecuencia_28d, frecuencia_mes, frecuencia_anyo,
             tiempo_estancia_min, histograma_estancia, visitas_horarias,
             boxplot_estancia,
             histograma_frecuencia_7d, histograma_frecuencia_28d,
             histograma_frecuencia_mes, histograma_frecuencia_anyo)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (fecha, zona_id) DO UPDATE SET
            total_visitas       = excluded.total_visitas,
            visitantes_unicos   = excluded.visitantes_unicos,
            visitantes_nuevos   = excluded.visitantes_nuevos,
            unicos_7d    = excluded.unicos_7d,    unicos_28d   = excluded.unicos_28d,
            unicos_mes   = excluded.unicos_mes,   unicos_anyo  = excluded.unicos_anyo,
            frecuencia_7d   = excluded.frecuencia_7d,  frecuencia_28d = excluded.frecuencia_28d,
            frecuencia_mes  = excluded.frecuencia_mes, frecuencia_anyo= excluded.frecuencia_anyo,
            tiempo_estancia_min       = excluded.tiempo_estancia_min,
            histograma_estancia       = excluded.histograma_estancia,
            visitas_horarias          = excluded.visitas_horarias,
            boxplot_estancia          = excluded.boxplot_estancia,
            histograma_frecuencia_7d  = excluded.histograma_frecuencia_7d,
            histograma_frecuencia_28d = excluded.histograma_frecuencia_28d,
            histograma_frecuencia_mes = excluded.histograma_frecuencia_mes,
            histograma_frecuencia_anyo = excluded.histograma_frecuencia_anyo
        """,
        rows,
    )


def actualizar_datos(
    ubicaciones_seleccionadas=None, stop_event=None, progress_cb=None, desde=None, hasta=None
):
    """
    Descarga datos de Aitanna y los persiste directamente en visitas (PostgreSQL).
    Incremental: solo descarga desde la última fecha registrada por location.
    desde/hasta (YYYY-MM-DD): fuerzan el rango ignorando ultima_fecha_db.
    """
    from src.db.queries import get_ultima_fecha_por_location
    from src.db.store import get_conn

    conn = get_conn()

    rows_ubi = conn.execute("SELECT ubicacion_id, org_id, nombre FROM ubicaciones").fetchall()
    org_map = {r[0]: r[1] for r in rows_ubi}
    name_map = {r[0]: r[2] for r in rows_ubi}

    ultima_fecha_db = get_ultima_fecha_por_location()

    location_ids = ubicaciones_seleccionadas if ubicaciones_seleccionadas else list(org_map.keys())
    if not location_ids:
        log.warning("No hay ubicaciones para sincronizar.")
        return

    fecha_fin = datetime.strptime(hasta, "%Y-%m-%d") if hasta else datetime.today()
    total_locs = len(location_ids)
    registros_nuevos_totales = 0

    log.info("Iniciando sync Aitanna — %d ubicación(es)", total_locs)

    for idx, loc_id in enumerate(location_ids, 1):
        if stop_event and stop_event.is_set():
            log.warning("Sincronización cancelada por stop_event.")
            break

        if progress_cb:
            progress_cb(idx, total_locs)

        nombre = name_map.get(loc_id, loc_id[:8])

        if desde:
            ultima_dt = datetime.strptime(desde, "%Y-%m-%d")
        else:
            ultima = ultima_fecha_db.get(loc_id)
            ultima_dt = (
                pd.to_datetime(ultima) if ultima else datetime.strptime("2024-01-01", "%Y-%m-%d")
            )

        dias_diferencia = (fecha_fin - ultima_dt).days
        if dias_diferencia <= 0:
            log.debug("[%d/%d] %s — al día, nada que descargar", idx, total_locs, nombre)
            continue

        fechas_a_descargar = [
            (fecha_fin - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(dias_diferencia + 1)
        ]

        log.info(
            "[%02d/%02d] %s — descargando %d día(s) (%s → %s)",
            idx,
            total_locs,
            nombre,
            len(fechas_a_descargar),
            fechas_a_descargar[-1],
            fechas_a_descargar[0],
        )

        filas_buffer = []
        errores_api: list[str] = []
        zone_enum_map: dict[str, int] = {}  # zone_uuid → zone enum from API
        org_uuid = org_map.get(loc_id, "")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futuros = [executor.submit(peticion_dia, loc_id, f) for f in fechas_a_descargar]
            for futuro in as_completed(futuros):
                fecha_str, datos, status = futuro.result()
                if status != "OK" or not datos:
                    if status != "404":
                        errores_api.append(f"{fecha_str}:{status}")
                    continue
                for zona in datos:
                    z_uuid = zona.get("zoneUUID", "")
                    z_enum = zona.get("zone")
                    if z_uuid and z_enum is not None:
                        zone_enum_map[z_uuid] = int(z_enum)
                    hours_data = zona.get("visitorsHour", [])
                    hourly_array = (
                        [
                            h.get("value", 0)
                            for h in sorted(hours_data, key=lambda x: x.get("hour", 0))
                        ]
                        if isinstance(hours_data, list)
                        else [0] * 24
                    )
                    filas_buffer.append(
                        (
                            fecha_str,
                            zona.get("zoneUUID", ""),
                            loc_id,
                            org_uuid,
                            int(zona.get("totalVisits", 0) or 0),
                            int(zona.get("uniqueVisitor", 0) or 0),
                            int(zona.get("newVisitor", 0) or 0),
                            float(zona.get("uniqueVisitorLast7days", 0) or 0),
                            float(zona.get("uniqueVisitorLast28days", 0) or 0),
                            float(zona.get("uniqueVisitorCurrentMonth", 0) or 0),
                            float(zona.get("uniqueVisitorCurrentYear", 0) or 0),
                            float(zona.get("frequencyLast7days", 0.0) or 0),
                            float(zona.get("frequencyLast28days", 0.0) or 0),
                            float(zona.get("frequencyCurrentMonth", 0.0) or 0),
                            float(zona.get("frequencyCurrentYear", 0.0) or 0),
                            float(zona.get("dwellTime", 0.0) or 0),
                            json.dumps(zona.get("dwellTimeHistogram") or []),
                            json.dumps(hourly_array),
                            json.dumps(zona.get("boxplot") or {}),
                            json.dumps(zona.get("frequencyLast7daysHistogram") or {}),
                            json.dumps(zona.get("frequencyLast28daysHistogram") or {}),
                            json.dumps(zona.get("frequencyCurrentMonthHistogram") or {}),
                            json.dumps(zona.get("frequencyCurrentYearHistogram") or {}),
                        )
                    )

        if errores_api:
            log.warning(
                "[%02d/%02d] %s — %d error(es) API: %s",
                idx,
                total_locs,
                nombre,
                len(errores_api),
                ", ".join(errores_api[:10]) + ("..." if len(errores_api) > 10 else ""),
            )

        if zone_enum_map:
            from src.db.store import get_conn as _gc

            _conn = _gc()
            for z_uuid, z_enum in zone_enum_map.items():
                _conn.execute(
                    "UPDATE zonas SET zone_enum = %s WHERE zona_id = %s AND (zone_enum IS NULL OR zone_enum != %s)",
                    [z_enum, z_uuid, z_enum],
                )

        if filas_buffer:
            _upsert_visitas(filas_buffer)
            registros_nuevos_totales += len(filas_buffer)
            log.info(
                "[%02d/%02d] %s — OK  +%d registros escritos",
                idx,
                total_locs,
                nombre,
                len(filas_buffer),
            )
        else:
            log.info("[%02d/%02d] %s — sin datos en el rango", idx, total_locs, nombre)

    log.info(
        "Sync Aitanna finalizada — %d ubicación(es), %d registros nuevos totales",
        total_locs,
        registros_nuevos_totales,
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Sincronizador Aitanna → visitas")
    parser.add_argument("--loc", nargs="+", metavar="UUID", help="location_uuid(s) a sincronizar")
    parser.add_argument("--desde", metavar="YYYY-MM-DD")
    parser.add_argument("--hasta", metavar="YYYY-MM-DD")
    args = parser.parse_args()
    actualizar_datos(
        ubicaciones_seleccionadas=args.loc,
        desde=args.desde,
        hasta=args.hasta,
    )
