import os
import re
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()

_URL_AITANNA   = 'https://platform.aitanna.ai/api/v1/get-all-locations-and-zones'
_NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
_NOMINATIM_UA  = 'agentic-workflow/1.0 (alvaro.salis@69summer.com)'

_COUNTRY_MAP = {
    'España': 'ES', 'Spain': 'ES',
    'México': 'MX', 'Mexico': 'MX',
    'Estados Unidos': 'US', 'USA': 'US', 'United States': 'US',
}

_PRESET_ES = {
    'rebajas_invierno': True, 'rebajas_verano': True,
    'black_friday': True, 'cyber_monday': True,
    'navidad_compras': True, 'reyes_compras': True,
    'san_valentin': True, 'dia_madre': True,
    'buen_fin_mx': False, 'dia_muertos': False,
    'independencia_mx': False, 'dia_madre_mx': False,
    'regreso_clases_mx': False, 'dia_nino_mx': False,
}

_PRESET_MX = {
    'rebajas_invierno': False, 'rebajas_verano': False,
    'black_friday': False, 'cyber_monday': True,
    'navidad_compras': True, 'reyes_compras': True,
    'san_valentin': True, 'dia_madre': False,
    'buen_fin_mx': True, 'dia_muertos': True,
    'independencia_mx': True, 'dia_madre_mx': True,
    'regreso_clases_mx': True, 'dia_nino_mx': True,
}

_PRESETS = {'ES': _PRESET_ES, 'MX': _PRESET_MX}


def _pais(loc: dict) -> str:
    if loc.get('country_code'):
        return loc['country_code'].upper()
    by_name = _COUNTRY_MAP.get(loc.get('country', ''), '')
    if by_name:
        return by_name
    addr = (loc.get('address') or '').lower()
    if any(k in addr for k in ('méxico', 'mexico', 'cdmx', 'ciudad de méxico')):
        return 'MX'
    if any(k in addr for k in ('españa', 'spain', 'madrid', 'barcelona', 'málaga', 'malaga')):
        return 'ES'
    return 'XX'


# ── Árbol de ubicaciones ──────────────────────────────────────────────────────

def descargar_maestro_ubicaciones():
    api_key = os.getenv('AITANNA_API_KEY')
    if not api_key:
        print('Error: AITANNA_API_KEY no encontrada en .env')
        return

    print('Descargando árbol de ubicaciones de Aitanna...')
    try:
        res = requests.get(_URL_AITANNA, headers={'x-api-key': api_key}, timeout=15)
    except requests.exceptions.Timeout:
        print('Error: timeout al conectar con la API.')
        return
    except Exception as e:
        print(f'Error de conexión: {e}')
        return

    if res.status_code != 200:
        print(f'Error HTTP {res.status_code}')
        return

    datos_frescos = res.json()

    from src.db.store import get_conn
    conn = get_conn()

    # Read existing geo memory from DB — preserve lat/lon and zone_type
    mem_locs = {
        r[0]: {'lat': r[1], 'lon': r[2], 'region_code': r[3], 'country_code': r[4], 'codigo_postal': r[5]}
        for r in conn.execute(
            "SELECT location_uuid, lat, lon, region_code, country_code, codigo_postal "
            "FROM dim_ubicaciones"
        ).fetchall()
        if r[1] is not None and r[2] is not None
    }
    mem_zones = {
        r[0]: r[1]
        for r in conn.execute("SELECT zone_uuid, zone_type FROM dim_zonas WHERE zone_type IS NOT NULL AND zone_type != ''").fetchall()
    }

    n_orgs = n_locs = n_zones = n_geo_rest = n_zt_rest = 0

    org_rows, loc_rows, zone_rows = [], [], []

    for org in datos_frescos:
        org_uuid = org.get('uuid')
        if not org_uuid:
            continue
        n_orgs += 1
        first_loc = org['locations'][0] if org.get('locations') else {}
        pais = _pais(first_loc)
        config = json.dumps(_PRESETS.get(pais, _PRESET_ES))
        org_rows.append((org_uuid, org['name'], pais, config))

        for loc in org.get('locations', []):
            n_locs += 1
            mem = mem_locs.get(loc['uuid'], {})
            lat = loc.get('lat') or mem.get('lat')
            lon = loc.get('lon') or mem.get('lon')
            if mem and lat:
                n_geo_rest += 1
            loc_pais = _pais(loc)
            loc_rows.append((
                loc['uuid'], org_uuid, loc['name'],
                lat, lon,
                loc.get('city'), loc.get('province'),
                loc_pais,
                loc.get('region_code') or mem.get('region_code'),
                loc.get('country_code') or mem.get('country_code'),
                loc.get('postCode') or loc.get('postal_code') or mem.get('codigo_postal'),
                loc.get('address'),
                True,
            ))

            for z in loc.get('zones', []):
                n_zones += 1
                zone_type = mem_zones.get(z['uuid'], z.get('zoneType', ''))
                if zone_type:
                    n_zt_rest += 1
                zone_rows.append((z['uuid'], loc['uuid'], z['zoneName'], z.get('hidden', False), zone_type or ''))

    conn.executemany(
        "INSERT INTO dim_organizaciones (org_uuid, nombre, pais_codigo, config_calendario) "
        "VALUES (?,?,?,?::jsonb) ON CONFLICT (org_uuid) DO UPDATE SET nombre = excluded.nombre, pais_codigo = excluded.pais_codigo",
        org_rows,
    )
    conn.executemany(
        "INSERT INTO dim_ubicaciones VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (location_uuid) DO UPDATE SET "
        "nombre = excluded.nombre, lat = COALESCE(excluded.lat, dim_ubicaciones.lat), "
        "lon = COALESCE(excluded.lon, dim_ubicaciones.lon), "
        "ciudad = excluded.ciudad, provincia = excluded.provincia, "
        "region_code = COALESCE(excluded.region_code, dim_ubicaciones.region_code), "
        "country_code = COALESCE(excluded.country_code, dim_ubicaciones.country_code), "
        "codigo_postal = COALESCE(excluded.codigo_postal, dim_ubicaciones.codigo_postal), "
        "direccion = excluded.direccion, activa = excluded.activa",
        loc_rows,
    )
    conn.executemany(
        "INSERT INTO dim_zonas (zone_uuid, location_uuid, nombre, hidden, zone_type) VALUES (?,?,?,?,?) "
        "ON CONFLICT (zone_uuid) DO UPDATE SET nombre = excluded.nombre, hidden = excluded.hidden, "
        "zone_type = CASE WHEN excluded.zone_type != '' THEN excluded.zone_type ELSE dim_zonas.zone_type END",
        zone_rows,
    )

    print('OK — árbol de ubicaciones actualizado en PostgreSQL.')
    print(f'  Organizaciones : {n_orgs}')
    print(f'  Ubicaciones    : {n_locs}  ({n_geo_rest} con geo preservada)')
    print(f'  Zonas          : {n_zones}  ({n_zt_rest} con zoneType preservado)')


# ── Geocodificación ───────────────────────────────────────────────────────────

def _limpiar(s):
    return re.sub(r'\s+', ' ', str(s or '').replace('\xa0', ' ')).strip()


def _candidatos_query(nombre, address, city, post_code, country):
    def _join(*partes):
        return ', '.join(p for p in partes if p)

    address   = _limpiar(address)
    city      = _limpiar(city)
    post_code = _limpiar(post_code)
    country   = _limpiar(country)
    nombre    = _limpiar(nombre)

    candidatos = []
    q = _join(address, city, post_code, country)
    if q:
        candidatos.append(q)
    if address and address not in (q,):
        candidatos.append(address)
    q3 = _join(nombre, city, country)
    if q3 and q3 not in candidatos:
        candidatos.append(q3)
    return candidatos


def _geocodificar_una(nombre, address, city, post_code, country, timeout=6):
    for i, query in enumerate(_candidatos_query(nombre, address, city, post_code, country)):
        if i > 0:
            time.sleep(1)
        try:
            r = requests.get(
                _NOMINATIM_URL,
                params={'q': query, 'format': 'json', 'limit': 1},
                headers={'User-Agent': _NOMINATIM_UA},
                timeout=timeout,
            )
            results = r.json()
            if results:
                return float(results[0]['lat']), float(results[0]['lon']), query
        except Exception:
            pass
    return None, None, None


def geocodificar_ubicaciones(solo_vacias=True):
    """Geocodifica ubicaciones sin coordenadas usando Nominatim (1 req/s)."""
    from src.db.store import get_conn
    conn = get_conn()

    rows = conn.execute(
        "SELECT location_uuid, nombre, direccion, ciudad, provincia, codigo_postal, country_code, lat, lon "
        "FROM dim_ubicaciones WHERE activa = TRUE"
    ).fetchall()

    pendientes = [r for r in rows if not solo_vacias or not (r[7] and r[8])]

    if not pendientes:
        print('Todas las ubicaciones ya tienen coordenadas.')
        return

    print(f'Geocodificando {len(pendientes)} ubicaciones (Nominatim, ~1 req/s)...')
    ok = fail = 0

    for loc_uuid, nombre, address, city, province, post_code, country_code, *_ in pendientes:
        lat, lon, query_usada = _geocodificar_una(
            nombre    = nombre or '',
            address   = address or '',
            city      = city or province or '',
            post_code = post_code or '',
            country   = country_code or '',
        )
        if lat is not None:
            conn.execute(
                "UPDATE dim_ubicaciones SET lat = ?, lon = ? WHERE location_uuid = ?",
                [round(lat, 6), round(lon, 6), loc_uuid],
            )
            print(f'  ✓  {nombre:<40} {lat:.5f}, {lon:.5f}')
            ok += 1
        else:
            print(f'  ✗  {nombre:<40} sin resultado')
            fail += 1
        time.sleep(1)

    print(f'\nGeocodificación completada: {ok} OK · {fail} sin resultado.')


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'todo'

    if cmd == 'arbol':
        descargar_maestro_ubicaciones()
    elif cmd == 'geo':
        geocodificar_ubicaciones()
    elif cmd == 'geo-todo':
        geocodificar_ubicaciones(solo_vacias=False)
    else:
        descargar_maestro_ubicaciones()
        print()
        geocodificar_ubicaciones()
