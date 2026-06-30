"""
Metro Bilbao — validaciones mensuales por estación (stub de catálogo).

Fuente: Metro Bilbao S.A. — portal de estadísticas.
  URL: https://www.metrobilbao.eus/metro-bilbao/cifras-y-estadisticas
  Formato: Datos anuales/mensuales publicados en web corporativa.

Cubre: Líneas 1 y 2. Centro Bilbao: Casco Viejo, Abando, Moyúa, Indautxu, Deusto.

Feature key: afluencia_metro_bio_{slug}
  Ej: afluencia_metro_bio_abando, afluencia_metro_bio_moyua

Configuración en location_source_config (source = 'metro_bilbao'):
  {
    "estaciones": [
      {"nombre": "Abando",  "slug": "abando"},
      {"nombre": "Moyúa",   "slug": "moyua"}
    ]
  }

NOTA: sync() no implementado — stub de catálogo para Context Scout.
"""

SOURCE = "metro_bilbao"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "afluencia_metro_bio_{slug}",
    "source": SOURCE,
    "categoria": "movilidad",
    "periodicidad": "mensual",
    "descripcion": (
        "Validaciones mensuales por estación de Metro Bilbao (L1 y L2). "
        "Mide accesos validados en la isócrona de la ubicación. "
        "Proxy directo del flujo peatonal en el área comercial de Bilbao. Nivel A."
    ),
    "url_referencia": "https://www.metrobilbao.eus/metro-bilbao/cifras-y-estadisticas",
    "url_descarga": "https://www.metrobilbao.eus/metro-bilbao/cifras-y-estadisticas",
    "granularidad": "estación (mensual, distribuida en días)",
    "cobertura_desde": "1995-11",
    "latencia_dias": 45,
    "notas_tecnicas": (
        "Datos publicados anualmente con desglose mensual. "
        "Solo incluir si la ubicación está a ≤800 m de una estación de Metro Bilbao. "
        "Zona comercial central: Abando (L1/L2), Moyúa (L1/L2), Indautxu (L1/L2), "
        "Casco Viejo (L1/L2), Deusto (L1)."
    ),
    "params_schema": (
        "{'estaciones': [{'nombre': '<nombre exacto de la estación Metro Bilbao>', "
        "'slug': '<snake_case del nombre>'}]}. "
        "Estaciones centro Bilbao: Casco Viejo, Abando, Moyúa, Indautxu, Deusto, "
        "San Mamés, Basurto, Bolueta, Etxebarri."
    ),
    "params_ejemplo": {
        "estaciones": [
            {"nombre": "Abando", "slug": "abando"},
            {"nombre": "Moyúa", "slug": "moyua"},
        ]
    },
}
