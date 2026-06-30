"""
Metrovalencia — validaciones mensuales por estación (FGV — stub de catálogo).

Fuente: Open Data FGV (Ferrocarrils de la Generalitat Valenciana).
  URL: https://www.fgv.es/es/metrovalencia/estadisticas
  Formato: Excel/CSV mensual publicado en portal de estadísticas FGV.

Cubre: Metro de Valencia (L1-L5, L9) y Tranvía (L4, T1, T2).

Feature key: afluencia_metrovalencia_{slug}
  Ej: afluencia_metrovalencia_colon, afluencia_metrovalencia_xativa

Configuración en location_source_config (source = 'metro_valencia'):
  {
    "estaciones": [
      {"nombre": "Colón",  "slug": "colon"},
      {"nombre": "Xàtiva", "slug": "xativa"}
    ]
  }

NOTA: sync() no implementado — stub de catálogo para Context Scout.
"""

SOURCE = "metro_valencia"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "afluencia_metrovalencia_{slug}",
    "source": SOURCE,
    "categoria": "movilidad",
    "periodicidad": "mensual",
    "descripcion": (
        "Validaciones mensuales por estación de Metrovalencia (FGV). "
        "Cubre metro y tranvía de Valencia. Mide accesos validados en la isócrona. "
        "Proxy directo del flujo peatonal en el área. Nivel A."
    ),
    "url_referencia": "https://www.fgv.es/es/metrovalencia/estadisticas",
    "url_descarga": "https://www.fgv.es/es/metrovalencia/estadisticas",
    "granularidad": "estación (mensual, distribuida en días)",
    "cobertura_desde": "2015-01",
    "latencia_dias": 45,
    "notas_tecnicas": (
        "Datos publicados en portal FGV. Sin autenticación. "
        "Incluir estaciones de metro y tranvía próximas a la ubicación. "
        "Líneas principales centro: L3, L5 (Colón, Xàtiva, Àngel Guimerà). "
        "Configurar 'estaciones' con nombre exacto tal como aparece en los datos FGV."
    ),
    "params_schema": (
        "{'estaciones': [{'nombre': '<nombre exacto en datos FGV>', "
        "'slug': '<snake_case del nombre>'}]}. "
        "Incluir las 2-4 estaciones de Metrovalencia a ≤800 m de las coordenadas. "
        "Estaciones frecuentes centro Valencia: Colón, Xàtiva, Àngel Guimerà, "
        "Túria, Alameda, Pont de Fusta."
    ),
    "params_ejemplo": {
        "estaciones": [
            {"nombre": "Colón", "slug": "colon"},
            {"nombre": "Xàtiva", "slug": "xativa"},
        ]
    },
}
