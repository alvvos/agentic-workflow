"""
Metro de Sevilla — validaciones mensuales por estación (stub de catálogo).

Fuente: Consorcio de Transportes Área de Sevilla / Metro de Sevilla S.A.
  URL: https://www.metro-sevilla.es/es/cifras
  Formato: Datos estadísticos publicados en web corporativa.

Cubre: Línea 1 (única línea operativa). Tramos: Olivar de Quintos ↔ Miraflores.
Estaciones en zona comercial centro: Puerta Jerez, Archivo de Indias, Centro-Sevilla.

Feature key: afluencia_metro_svq_{slug}
  Ej: afluencia_metro_svq_puerta_jerez, afluencia_metro_svq_centro_sevilla

Configuración en location_source_config (source = 'metro_sevilla'):
  {
    "estaciones": [
      {"nombre": "Puerta Jerez",   "slug": "puerta_jerez"},
      {"nombre": "Centro-Sevilla", "slug": "centro_sevilla"}
    ]
  }

NOTA: sync() no implementado — stub de catálogo para Context Scout.
"""

SOURCE = "metro_sevilla"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "afluencia_metro_svq_{slug}",
    "source": SOURCE,
    "categoria": "movilidad",
    "periodicidad": "mensual",
    "descripcion": (
        "Validaciones mensuales por estación de Metro de Sevilla (Línea 1). "
        "Mide accesos validados en estaciones próximas a la ubicación. "
        "Proxy del flujo peatonal en el eje comercial de Sevilla. Nivel A. "
        "Solo aplica a ubicaciones en la Línea 1 (Olivar de Quintos ↔ Miraflores)."
    ),
    "url_referencia": "https://www.metro-sevilla.es/es/cifras",
    "url_descarga": "https://www.metro-sevilla.es/es/cifras",
    "granularidad": "estación (mensual, distribuida en días)",
    "cobertura_desde": "2009-04",
    "latencia_dias": 45,
    "notas_tecnicas": (
        "Metro de Sevilla tiene una única línea (L1). "
        "Solo incluir si la ubicación está a ≤800 m de una estación de L1. "
        "Estaciones zona comercial: Puerta Jerez, Archivo de Indias, Centro-Sevilla, "
        "Prado de San Sebastián, Plaza de Cuba."
    ),
    "params_schema": (
        "{'estaciones': [{'nombre': '<nombre exacto de la estación Metro Sevilla>', "
        "'slug': '<snake_case del nombre>'}]}. "
        "Estaciones L1: Olivar de Quintos, Ciudad Expo, Palacio de Congresos, "
        "Estadio Olímpico, Parque de los Príncipes, San Bernardo, Puerta Jerez, "
        "Archivo de Indias, Centro-Sevilla, Prado de San Sebastián, Plaza de Cuba, "
        "Neptuno, El Greco, Blas Infante, Padre Pío, Miraflores."
    ),
    "params_ejemplo": {
        "estaciones": [
            {"nombre": "Puerta Jerez", "slug": "puerta_jerez"},
            {"nombre": "Centro-Sevilla", "slug": "centro_sevilla"},
        ]
    },
}
