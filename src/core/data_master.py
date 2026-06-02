"""
Mapas de dimensiones en memoria, alimentados desde DuckDB.
La API exportada es idéntica a la versión JSON para que los callbacks no necesiten cambios.
"""
import time

# Los módulos externos importan estas variables directamente.
# Se mutan en lugar de reasignarse para que los módulos ya importados vean los cambios.
opciones_orgs:      list = []
mapa_locs_por_org:  dict = {}
mapa_tiendas:       dict = {}
mapa_zonas:         dict = {}
mapa_zonas_por_loc: dict = {}
mapa_orgs:          dict = {}

_last_load: float = 0.0
_TTL = 5.0  # segundos mínimos entre recargas


def _load_from_db() -> None:
    from src.db.store import get_conn
    conn = get_conn()

    opciones_orgs.clear()
    mapa_locs_por_org.clear()
    mapa_tiendas.clear()
    mapa_zonas.clear()
    mapa_zonas_por_loc.clear()
    mapa_orgs.clear()

    for org_uuid, nombre in conn.execute(
        "SELECT org_uuid, nombre FROM dim_organizaciones ORDER BY nombre"
    ).fetchall():
        opciones_orgs.append({'label': nombre, 'value': org_uuid})
        mapa_orgs[org_uuid] = nombre
        mapa_locs_por_org[org_uuid] = []

    for loc_uuid, org_uuid, nombre in conn.execute(
        "SELECT location_uuid, org_uuid, nombre FROM dim_ubicaciones WHERE activa = TRUE ORDER BY nombre"
    ).fetchall():
        mapa_tiendas[loc_uuid] = nombre
        mapa_locs_por_org.setdefault(org_uuid, []).append({'label': nombre, 'value': loc_uuid})
        mapa_zonas_por_loc[loc_uuid] = []

    for zone_uuid, loc_uuid, nombre, zone_type in conn.execute(
        "SELECT zone_uuid, location_uuid, nombre, zone_type FROM dim_zonas WHERE hidden = FALSE ORDER BY nombre"
    ).fetchall():
        mapa_zonas[zone_uuid] = nombre
        mapa_zonas_por_loc.setdefault(loc_uuid, []).append({
            'label': nombre,
            'value': nombre,        # los dropdowns BI usan el nombre como valor
            'tipo':  zone_type or '',
        })


def reload_if_changed() -> bool:
    """Recarga desde DuckDB con TTL de 5 s. Devuelve True si recargó."""
    global _last_load
    now = time.time()
    if now - _last_load < _TTL:
        return False
    try:
        _load_from_db()
        _last_load = now
        return True
    except Exception:
        return False


# Carga inicial al importar el módulo
try:
    _load_from_db()
    _last_load = time.time()
except Exception:
    pass
