import os
import re
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()

_RUTA_JSON     = 'src/data/todas_las_ubicaciones.json'
_URL_AITANNA   = 'https://platform.aitanna.ai/api/v1/get-all-locations-and-zones'
_NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
_NOMINATIM_UA  = 'agentic-workflow/1.0 (alvaro.salis@69summer.com)'

_CAMPOS_GEO = ('lat', 'lon', 'postal_code', 'region_code', 'country_code')


# ── Árbol de ubicaciones ──────────────────────────────────────────────────────

def _cargar_memorias(ruta):
    """
    Lee el JSON existente y devuelve:
      - memoria_locs:  uuid_loc  → {lat, lon, ...}  (campos geo manuales)
      - memoria_zones: uuid_zone → zoneType          (la API dejó de devolverlo)
    """
    memoria_locs  = {}
    memoria_zones = {}
    if not os.path.exists(ruta):
        return memoria_locs, memoria_zones
    with open(ruta, encoding='utf-8') as f:
        datos = json.load(f)
    for org in datos:
        for loc in org.get('locations', []):
            geo = {k: loc[k] for k in _CAMPOS_GEO if k in loc}
            if geo:
                memoria_locs[loc['uuid']] = geo
            for z in loc.get('zones', []):
                if 'zoneType' in z:
                    memoria_zones[z['uuid']] = z['zoneType']
    return memoria_locs, memoria_zones


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
    memoria_locs, memoria_zones = _cargar_memorias(_RUTA_JSON)

    n_orgs = n_locs = n_zones = 0
    n_geo_rest = n_zt_rest = 0

    for org in datos_frescos:
        n_orgs += 1
        for loc in org.get('locations', []):
            n_locs += 1
            if loc['uuid'] in memoria_locs:
                loc.update(memoria_locs[loc['uuid']])
                n_geo_rest += 1
            for z in loc.get('zones', []):
                n_zones += 1
                if z['uuid'] in memoria_zones:
                    z['zoneType'] = memoria_zones[z['uuid']]
                    n_zt_rest += 1

    with open(_RUTA_JSON, 'w', encoding='utf-8') as f:
        json.dump(datos_frescos, f, ensure_ascii=False, indent=4)

    print(f'OK — {_RUTA_JSON} actualizado.')
    print(f'  Organizaciones : {n_orgs}')
    print(f'  Ubicaciones    : {n_locs}  ({n_geo_rest} con geo preservada)')
    print(f'  Zonas          : {n_zones}  ({n_zt_rest} con zoneType preservado)')


# ── Geocodificación ───────────────────────────────────────────────────────────

def _limpiar(s):
    """Elimina espacios de no separación y espacios extra."""
    return re.sub(r'\s+', ' ', str(s or '').replace('\xa0', ' ')).strip()


def _candidatos_query(nombre, address, city, post_code, country):
    """
    Genera queries de geocodificación en orden de especificidad descendente.
    Usa solo los campos no vacíos.
    """
    def _join(*partes):
        return ', '.join(p for p in partes if p)

    address  = _limpiar(address)
    city     = _limpiar(city)
    post_code = _limpiar(post_code)
    country  = _limpiar(country)
    nombre   = _limpiar(nombre)

    candidatos = []

    # 1. Dirección completa + ciudad + CP + país
    q = _join(address, city, post_code, country)
    if q:
        candidatos.append(q)

    # 2. Solo dirección (muchas ya son completas con CP y ciudad incluidas)
    if address and address not in (q,):
        candidatos.append(address)

    # 3. Nombre + ciudad + país (fallback sin dirección)
    q3 = _join(nombre, city, country)
    if q3 and q3 not in candidatos:
        candidatos.append(q3)

    return candidatos


def _geocodificar_una(nombre, address, city, post_code, country, timeout=6):
    """
    Llama a Nominatim con queries progresivas.
    Respeta el rate limit de 1 req/s entre intentos.
    """
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
    """
    Añade lat/lon a las ubicaciones que carecen de coordenadas.
    Usa Nominatim (OpenStreetMap) — gratuito, límite 1 req/s.

    solo_vacias=True  → salta las que ya tienen lat/lon
    solo_vacias=False → regeocifica todas
    """
    with open(_RUTA_JSON, encoding='utf-8') as f:
        data = json.load(f)

    pendientes = [
        loc
        for org in data
        for loc in org.get('locations', [])
        if not solo_vacias or not (loc.get('lat') and loc.get('lon'))
    ]

    if not pendientes:
        print('Todas las ubicaciones ya tienen coordenadas.')
        return

    print(f'Geocodificando {len(pendientes)} ubicaciones (Nominatim, ~1 req/s)...')
    ok = fail = 0

    for loc in pendientes:
        lat, lon, query_usada = _geocodificar_una(
            nombre    = loc.get('name', ''),
            address   = loc.get('address', ''),
            city      = loc.get('city', ''),
            post_code = loc.get('postCode', ''),
            country   = loc.get('country', ''),
        )
        if lat is not None:
            loc['lat'] = round(lat, 6)
            loc['lon'] = round(lon, 6)
            print(f'  ✓  {loc["name"]:<40} {lat:.5f}, {lon:.5f}')
            ok += 1
        else:
            print(f'  ✗  {loc["name"]:<40} sin resultado')
            fail += 1
        time.sleep(1)  # rate limit Nominatim

    with open(_RUTA_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

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
