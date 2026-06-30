"""
Cercanías Renfe — validaciones mensuales por estación (stub de catálogo).

Fuente: Renfe Viajeros — portal de datos estadísticos.
  URL: https://www.renfe.com/es/es/grupo-renfe/informacion-corporativa/renfe-en-cifras
  Formato: Informes anuales con desglose por núcleo y estación.

Núcleos (siglas Renfe): ML (Málaga), MD (Madrid — preferir metro_madrid),
  C (Cataluña/Barcelona — preferir metro_barcelona), AS (Asturias),
  VL (Valencia — valorar frente a metro_valencia), MU (Murcia),
  CZ (Cádiz), SE (Sevilla — complementa metro_sevilla), ZR (Zaragoza).

Feature key: afluencia_cercanias_{nucleo_lower}_{slug}
  Ej: afluencia_cercanias_ml_centro_alameda (Málaga Centro-Alameda)

Configuración en location_source_config (source = 'cercanias_renfe'):
  {
    "nucleo": "ML",
    "estaciones": [
      {"nombre": "Málaga-Centro Alameda", "slug": "malaga_centro_alameda"},
      {"nombre": "Málaga-María Zambrano", "slug": "malaga_maria_zambrano"}
    ]
  }

NOTA: sync() no implementado — stub de catálogo para Context Scout.
Usar solo en ciudades SIN metro propio (Málaga, Murcia, Cádiz, Zaragoza...).
En Madrid/Barcelona/Valencia/Bilbao/Sevilla priorizar el metro de la ciudad.
"""

SOURCE = "cercanias_renfe"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "afluencia_cercanias_{nucleo_lower}_{slug}",
    "source": SOURCE,
    "categoria": "movilidad",
    "periodicidad": "mensual",
    "descripcion": (
        "Validaciones mensuales por estación de Cercanías Renfe. "
        "Proxy directo del flujo de viajeros por la estación más próxima a la ubicación. "
        "Señal de nivel A en ciudades sin metro propio (Málaga, Murcia, Cádiz...). "
        "En ciudades con metro, priorizar la fuente de metro sobre cercanías."
    ),
    "url_referencia": "https://www.renfe.com/es/es/grupo-renfe/informacion-corporativa/renfe-en-cifras",
    "url_descarga": "https://www.renfe.com/es/es/grupo-renfe/informacion-corporativa/renfe-en-cifras",
    "granularidad": "estación (mensual, distribuida en días)",
    "cobertura_desde": "2010-01",
    "latencia_dias": 60,
    "notas_tecnicas": (
        "Datos publicados en informes anuales Renfe. Granularidad por núcleo y estación. "
        "Usar solo si la ubicación está a ≤800 m de una estación de cercanías Y la ciudad "
        "no tiene red de metro propia (en ese caso usar metro_* de la ciudad). "
        "Especificar nucleo (sigla Renfe) y lista de estaciones más próximas."
    ),
    "params_schema": (
        "{'nucleo': '<sigla del núcleo Renfe — ML, MD, C, AS, VL, MU, CZ, SE, ZR>', "
        "'estaciones': [{'nombre': '<nombre exacto en datos Renfe>', "
        "'slug': '<snake_case del nombre>'}]}. "
        "Solo incluir si ciudad sin metro propio. "
        "Málaga: nucleo=ML, estaciones principales: Málaga-Centro Alameda, Málaga-María Zambrano."
    ),
    "params_ejemplo": {
        "nucleo": "ML",
        "estaciones": [
            {"nombre": "Málaga-Centro Alameda", "slug": "malaga_centro_alameda"},
            {"nombre": "Málaga-María Zambrano", "slug": "malaga_maria_zambrano"},
        ],
    },
}
