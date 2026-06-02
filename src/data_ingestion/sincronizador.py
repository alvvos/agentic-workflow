import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")


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
        INSERT INTO fact_visitas
            (fecha, zone_uuid, location_uuid, org_uuid,
             total_visits, unique_visitors, new_visitors,
             uv_7d, uv_28d, uv_month, uv_year,
             freq_7d, freq_28d, freq_month, freq_year,
             dwell_time_min, dwell_hist, hourly_visits)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (fecha, zone_uuid) DO UPDATE SET
            total_visits    = excluded.total_visits,
            unique_visitors = excluded.unique_visitors,
            new_visitors    = excluded.new_visitors,
            uv_7d = excluded.uv_7d, uv_28d = excluded.uv_28d,
            uv_month = excluded.uv_month, uv_year = excluded.uv_year,
            freq_7d = excluded.freq_7d, freq_28d = excluded.freq_28d,
            freq_month = excluded.freq_month, freq_year = excluded.freq_year,
            dwell_time_min = excluded.dwell_time_min,
            dwell_hist = excluded.dwell_hist,
            hourly_visits = excluded.hourly_visits
        """,
        rows,
    )


def actualizar_datos(ubicaciones_seleccionadas=None, stop_event=None, progress_cb=None):
    """
    Descarga datos de Aitanna y los persiste directamente en fact_visitas (PostgreSQL).
    Incremental: solo descarga desde la última fecha registrada por location.
    """
    from src.db.store import get_conn
    from src.db.queries import get_ultima_fecha_por_location

    conn = get_conn()

    # org_uuid map para el INSERT
    org_map = dict(conn.execute(
        "SELECT location_uuid, org_uuid FROM dim_ubicaciones"
    ).fetchall())

    ultima_fecha_db = get_ultima_fecha_por_location()

    location_ids = ubicaciones_seleccionadas if ubicaciones_seleccionadas else list(org_map.keys())
    if not location_ids:
        print("No hay ubicaciones para sincronizar.")
        return

    fecha_hoy = datetime.today()
    total_locs = len(location_ids)
    registros_nuevos_totales = 0

    for idx, loc_id in enumerate(location_ids, 1):
        if stop_event and stop_event.is_set():
            print("Sincronización cancelada.")
            break

        if progress_cb:
            progress_cb(idx, total_locs)

        ultima = ultima_fecha_db.get(loc_id)
        if ultima:
            ultima_dt = pd.to_datetime(ultima)
        else:
            ultima_dt = datetime.strptime("2024-01-01", "%Y-%m-%d")

        dias_diferencia = (fecha_hoy - ultima_dt).days
        if dias_diferencia <= 0:
            continue

        fechas_a_descargar = [
            (fecha_hoy - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(dias_diferencia + 1)
        ]

        print(f"[{idx:02d}/{total_locs}] {loc_id[:8]}... | {len(fechas_a_descargar)} días", end="\r")

        filas_buffer = []
        org_uuid = org_map.get(loc_id, '')

        with ThreadPoolExecutor(max_workers=5) as executor:
            futuros = [executor.submit(peticion_dia, loc_id, f) for f in fechas_a_descargar]
            for futuro in as_completed(futuros):
                fecha_str, datos, status = futuro.result()
                if status != "OK" or not datos:
                    continue
                for zona in datos:
                    hours_data = zona.get("visitorsHour", [])
                    hourly_array = (
                        [h.get("value", 0) for h in sorted(hours_data, key=lambda x: x.get("hour", 0))]
                        if isinstance(hours_data, list) else [0] * 24
                    )
                    filas_buffer.append((
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
                        str(zona.get("dwellTimeHistogram", [])),
                        str(hourly_array),
                    ))

        if filas_buffer:
            _upsert_visitas(filas_buffer)
            registros_nuevos_totales += len(filas_buffer)
            print(f"[{idx:02d}/{total_locs}] {loc_id[:8]}... | +{len(filas_buffer)} registros guardados.")
        else:
            print(f"[{idx:02d}/{total_locs}] {loc_id[:8]}... | Sin datos.              ")

    print(f"\nSincronización finalizada. Registros nuevos: {registros_nuevos_totales}")


if __name__ == "__main__":
    actualizar_datos()
