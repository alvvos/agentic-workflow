import json
import os

_UBIC_PATH = 'src/data/todas_las_ubicaciones.json'
_mtime: float = 0.0

# Módulos externos importan estas variables directamente (from data_master import ...).
# Se mutan en lugar de reasignarse para que los módulos ya importados vean los cambios.
opciones_orgs:     list = []
mapa_locs_por_org: dict = {}
mapa_tiendas:      dict = {}
mapa_zonas:        dict = {}
mapa_zonas_por_loc: dict = {}
mapa_orgs:         dict = {}


def _parse(datos_loc: list) -> None:
    opciones_orgs.clear()
    mapa_locs_por_org.clear()
    mapa_tiendas.clear()
    mapa_zonas.clear()
    mapa_zonas_por_loc.clear()
    mapa_orgs.clear()

    for org in datos_loc:
        if not org.get('uuid'):
            continue
        opciones_orgs.append({'label': org.get('name'), 'value': org['uuid']})
        mapa_orgs[org['uuid']] = org.get('name', '')
        locs_list = []
        for loc in org.get('locations', []):
            if not loc.get('uuid'):
                continue
            locs_list.append({'label': loc.get('name'), 'value': loc['uuid']})
            mapa_tiendas[loc['uuid']] = loc.get('name')
            zonas_loc = []
            for z in loc.get('zones', []):
                if z.get('uuid'):
                    nombre_zona = z.get('zoneName', 'Zona')
                    mapa_zonas[z['uuid']] = nombre_zona
                    zonas_loc.append({
                        'label': nombre_zona,
                        'value': nombre_zona,
                        'tipo':  z.get('zoneType', ''),
                    })
            mapa_zonas_por_loc[loc['uuid']] = zonas_loc
        mapa_locs_por_org[org['uuid']] = locs_list


def reload_if_changed() -> bool:
    """Re-lee el JSON solo si el archivo cambió en disco. Devuelve True si recargó."""
    global _mtime
    try:
        mtime = os.path.getmtime(_UBIC_PATH)
    except OSError:
        return False
    if mtime == _mtime:
        return False
    with open(_UBIC_PATH, 'r', encoding='utf-8') as f:
        _parse(json.load(f))
    _mtime = mtime
    return True


# Carga inicial al importar el módulo
reload_if_changed()
