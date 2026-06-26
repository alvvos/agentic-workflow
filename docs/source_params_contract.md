# Contrato de parámetros por fuente — `location_source_config`

Cada ingestor lee sus parámetros específicos de `location_source_config` en lugar
de hardcodearlos. El scout agent es responsable de descubrir y escribir estos
parámetros para cada ubicación nueva.

## Convención general

Los parámetros **universales** (lat, lon, pais_codigo, region_code) viven en
`dim_ubicaciones` y los ingestores los leen directamente de ahí. Aquí solo van
los parámetros que son **específicos de la fuente** y que varían por ubicación
de forma no predecible.

---

## Fuentes activas

### `puertos_estado`
Estadística mensual oficial de pasajeros de crucero — Puertos del Estado (XLSX).

| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `port_authority` | string | ✓ | Nombre exacto de la AP tal como aparece en la hoja "Pasajeros crucero" del XLSX. Ej: `"Málaga"`, `"Barcelona"`, `"Valencia"` |

```json
{ "port_authority": "Málaga" }
```

Aplica a: ubicaciones en puertos españoles con escalas de crucero.
Fuente: `https://www.puertos.es/en/data/statistics/monthly`

---

### `cruceros`
Previsión contractual de escalas del portal propio del puerto (calendario).

| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `ajax_url` | string | ✓ | Endpoint AJAX del portal del puerto |
| `ajax_action` | string | ✓ | Valor del campo `action` en el POST |

```json
{
  "ajax_url": "https://www.puertomalaga.com/wp-admin/admin-ajax.php",
  "ajax_action": "get_prevision_turistas_by_date"
}
```

Aplica a: puertos que publican su previsión de escalas via WP-AJAX.
Nota: si el puerto no usa este sistema, la fuente no es aplicable y no debe
registrarse en `location_source_config`.

---

### `open_holidays`
Festivos y vacaciones escolares — Open Holidays API.

No requiere entrada en `location_source_config`. Lee `pais_codigo` y
`region_code` directamente de `dim_ubicaciones`.

---

### `ticketmaster`
Eventos (conciertos, deportes, festivales) via Ticketmaster Discovery API.

| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `radius_km` | int | ✗ | Radio de búsqueda en km. Default: 10 |

```json
{ "radius_km": 10 }
```

Si no hay entrada en `location_source_config`, el ingestor usa el default.
Lee lat/lon de `dim_ubicaciones`.

---

### `weather`
Datos históricos de clima — Open-Meteo API.

No requiere entrada en `location_source_config`. Lee lat/lon de
`dim_ubicaciones`.

---

## Fuentes planificadas (pendiente de implementar)

### `ine` — Instituto Nacional de Estadística (España)
| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `municipio_code` | string | ✓ | Código INE de municipio. Ej: `"29067"` (Málaga) |
| `provincia_code` | string | ✓ | Código de provincia (2 dígitos). Ej: `"29"` |
| `ccaa_code` | string | ✗ | Código de CCAA. Ej: `"01"` (Andalucía) |

```json
{ "municipio_code": "29067", "provincia_code": "29", "ccaa_code": "01" }
```

### `sepe` — Servicio Público de Empleo Estatal (España)
| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `municipio_code` | string | ✓ | Mismo código que INE |
| `provincia_code` | string | ✓ | Código de provincia |

```json
{ "municipio_code": "29067", "provincia_code": "29" }
```

### `insee` — Institut national de la statistique (Francia)
| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `commune_code` | string | ✓ | Código INSEE de commune. Ej: `"56069"` |
| `departement` | string | ✗ | Código de departamento |

```json
{ "commune_code": "56069", "departement": "56" }
```

### `inegi` — Instituto Nacional de Estadística, Geografía e Informática (México)
| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `entidad_clave` | string | ✓ | Clave de entidad federativa. Ej: `"06"` (Colima) |
| `municipio_clave` | string | ✓ | Clave de municipio. Ej: `"06002"` |

```json
{ "entidad_clave": "06", "municipio_clave": "06002" }
```

### `ons` — Office for National Statistics (UK)
| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `oa_code` | string | ✓ | Output Area code. Ej: `"E02006889"` |
| `lsoa_code` | string | ✗ | Lower Super Output Area |

```json
{ "oa_code": "E02006889" }
```

### `metro` — Validaciones de metro (específico por red)
| Clave | Tipo | Req | Descripción |
|---|---|---|---|
| `network` | string | ✓ | `"madrid"`, `"barcelona"`, `"bilbao"`, `"valencia"` |
| `station_slugs` | array | ✓ | Identificadores de estaciones próximas a la ubicación |

```json
{ "network": "madrid", "station_slugs": ["gran_via_l1", "gran_via_l5"] }
```

---

## Responsabilidades

| Quién | Qué |
|---|---|
| **Scout agent** | Descubre los parámetros correctos para cada (location, source) nueva. Valida que los datos obtenidos son coherentes. Escribe en `location_source_config` con `configurado_por='scout'`. |
| **Ingestores** | Leen de `location_source_config`. No hardcodean ningún parámetro de ubicación. Si no hay entrada para una (location, source), la ubicación se omite silenciosamente. |
| **Deploy / manual** | Puede sobreescribir parámetros incorrectos del scout. Usa `configurado_por='manual'`. |

## Patrón de lectura en ingestores

```python
def _get_source_params(location_uuid: str, source: str) -> dict | None:
    row = get_conn().execute(
        "SELECT params FROM location_source_config "
        "WHERE location_uuid = ? AND source = ? AND activo = TRUE",
        [location_uuid, source],
    ).fetchone()
    return row[0] if row else None
```

Si retorna `None`, el ingestor salta esa ubicación sin error.
