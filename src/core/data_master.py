import json

with open('src/data/todas_las_ubicaciones.json', 'r', encoding='utf-8') as f:
    datos_loc = json.load(f)

opciones_orgs = []
mapa_locs_por_org = {}
mapa_tiendas = {}
mapa_zonas = {}
mapa_zonas_por_loc = {}
mapa_orgs = {}

for org in datos_loc:
    if org.get('uuid'):
        opciones_orgs.append({'label': org.get('name'), 'value': org['uuid']})
        mapa_orgs[org['uuid']] = org.get('name', '')
        locs_list = []
        for loc in org.get('locations', []):
            if loc.get('uuid'):
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
                            'tipo': z.get('zoneType', '')
                        })
                mapa_zonas_por_loc[loc['uuid']] = zonas_loc

        mapa_locs_por_org[org['uuid']] = locs_list
