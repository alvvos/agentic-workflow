"""
Mapas de dimensiones en memoria, alimentados desde DuckDB.
La API exportada es idéntica a la versión JSON para que los callbacks no necesiten cambios.
"""
import time

# Los módulos externos importan estas variables directamente.
# Se mutan en lugar de reasignarse para que los módulos ya importados vean los cambios.
opciones_orgs:       list = []
mapa_locs_por_org:   dict = {}
mapa_tiendas:        dict = {}
mapa_zonas:          dict = {}
mapa_zonas_por_loc:  dict = {}
mapa_orgs:           dict = {}
mapa_hijos_por_zona: dict = {}  # {loc_uuid: {parent_zone_name: [child_zone_dicts]}}

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
    mapa_hijos_por_zona.clear()

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

    all_zones = conn.execute(
        "SELECT zone_uuid, location_uuid, nombre, zone_type, parent_zone_uuid"
        " FROM dim_zonas WHERE hidden = FALSE ORDER BY nombre"
    ).fetchall()

    # First pass: build uuid→name map so child zones can resolve parent name
    for zone_uuid, _, nombre, _, _ in all_zones:
        mapa_zonas[zone_uuid] = nombre

    # Second pass: classify parent vs child
    for zone_uuid, loc_uuid, nombre, zone_type, parent_uuid in all_zones:
        z = {
            'label':      nombre,
            'value':      nombre,
            'tipo':       zone_type or '',
            'padre_uuid': parent_uuid,
        }
        mapa_zonas_por_loc.setdefault(loc_uuid, []).append(z)
        if parent_uuid:
            parent_name = mapa_zonas.get(parent_uuid, parent_uuid)
            mapa_hijos_por_zona.setdefault(loc_uuid, {}).setdefault(parent_name, []).append(z)


def get_opciones_orgs_for_user(org_access: list | None) -> list:
    """Devuelve las opciones de org filtradas por acceso. None → admin (ve todo)."""
    if org_access is None:
        return list(opciones_orgs)
    allowed = set(org_access)
    return [o for o in opciones_orgs if o['value'] in allowed]


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
