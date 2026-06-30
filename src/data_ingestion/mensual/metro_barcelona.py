"""
Metro de Barcelona — validaciones mensuales por estación (TMB — stub de catálogo).

Fuente: Open Data TMB (Transports Metropolitans de Barcelona).
  URL: https://developer.tmb.cat/data/validaciones-metro
  Formato: CSV/API mensual con autenticación (app_id + app_key gratuitos).

Feature key: afluencia_metro_bcn_{slug}
  Ej: afluencia_metro_bcn_passeig_gracia, afluencia_metro_bcn_diagonal

Configuración en location_source_config (source = 'metro_barcelona'):
  {
    "estaciones": [
      {"nombre": "Passeig de Gràcia", "slug": "passeig_gracia"},
      {"nombre": "Diagonal",          "slug": "diagonal"}
    ]
  }

NOTA: sync() no implementado — stub de catálogo para Context Scout.
"""

SOURCE = "metro_barcelona"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "afluencia_metro_bcn_{slug}",
    "source": SOURCE,
    "categoria": "movilidad",
    "periodicidad": "mensual",
    "descripcion": (
        "Validaciones mensuales por estación de Metro de Barcelona (TMB). "
        "Mide el número de accesos validados en cada estación dentro de la isócrona. "
        "Proxy directo del volumen de peatones que transitan por el área. Nivel A."
    ),
    "url_referencia": "https://developer.tmb.cat/data/validaciones-metro",
    "url_descarga": "https://developer.tmb.cat/data/validaciones-metro",
    "granularidad": "estación (mensual, distribuida en días)",
    "cobertura_desde": "2018-01",
    "latencia_dias": 45,
    "notas_tecnicas": (
        "Requiere registro gratuito en developer.tmb.cat para obtener app_id + app_key. "
        "Configurar 'estaciones' con las 2-4 estaciones de metro TMB más cercanas a la ubicación. "
        "Líneas TMB: L1 (roja), L2 (morada), L3 (verde), L4 (amarilla), L5 (azul). "
        "No incluir estaciones FGC (Ferrocarrils de la Generalitat) — operador diferente."
    ),
    "params_schema": (
        "{'estaciones': [{'nombre': '<nombre exacto de la estación en datos TMB>', "
        "'slug': '<snake_case del nombre>'}]}. "
        "Incluir las 2-4 estaciones de Metro TMB a ≤800 m de las coordenadas. "
        "Estaciones frecuentes en zona centro: Passeig de Gràcia, Diagonal, Universitat, "
        "Catalunya, Liceu, Jaume I, Barceloneta, Arc de Triomf, Urquinaona."
    ),
    "params_ejemplo": {
        "estaciones": [
            {"nombre": "Passeig de Gràcia", "slug": "passeig_gracia"},
            {"nombre": "Diagonal", "slug": "diagonal"},
        ]
    },
}
