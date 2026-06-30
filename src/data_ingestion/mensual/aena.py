"""
AENA — Pasajeros de aeropuerto (stub de catálogo — ingestor pendiente).

Fuente: Portal de estadísticas AENA.
  URL: https://www.aena.es/es/corporativa/estadisticas.html
  Formato: Excel mensual sin autenticación (~día 20 del mes siguiente).

Feature key: aena_pasajeros_{iata_lower}
  Ej: aena_pasajeros_agp (Málaga), aena_pasajeros_mad (Madrid), aena_pasajeros_bcn (Barcelona)

Configuración en location_source_config (source = 'aena'):
  {
    "iata": "AGP",
    "aeropuerto_nombre": "Málaga-Costa del Sol"
  }

El campo 'iata' es el código IATA de 3 letras del aeropuerto que sirve a la ciudad.
El campo 'aeropuerto_nombre' es opcional (para trazabilidad).

NOTA: sync() no implementado — este módulo solo expone CATALOG_ENTRY para Context Scout.
Cuando se implemente el ingestor, añadir SOURCE, sync() y este comentario desaparece.
"""

SOURCE = "aena"

CATALOG_PAISES = ["ES"]

CATALOG_ENTRY = {
    "feature_key_template": "aena_pasajeros_{iata_lower}",
    "source": SOURCE,
    "categoria": "turismo",
    "periodicidad": "mensual",
    "descripcion": (
        "Pasajeros totales (llegadas + salidas) en el aeropuerto que sirve a la ciudad — AENA. "
        "Cuenta personas reales que aterrizan o despegan en el aeropuerto de la ciudad cada mes. "
        "Proxy directo del volumen de visitantes y turistas que entran en el área de influencia "
        "de la ubicación. Señal de nivel A: máxima directitud."
    ),
    "url_referencia": "https://www.aena.es/es/corporativa/estadisticas.html",
    "url_descarga": "https://www.aena.es/es/corporativa/estadisticas.html",
    "granularidad": "aeropuerto (ciudad)",
    "cobertura_desde": "2000-01",
    "latencia_dias": 20,
    "notas_tecnicas": (
        "Publicado ~día 20 del mes siguiente. Descarga Excel desde portal AENA estadísticas. "
        "Sin autenticación. Solo incluir si la ciudad tiene aeropuerto con tráfico turístico "
        "significativo (>1M pax/año) y la ubicación está en zona de influencia del flujo de "
        "visitantes (centros urbanos, centros comerciales, zonas turísticas). "
        "No incluir en ciudades con aeropuerto regional de muy bajo tráfico."
    ),
    "params_schema": (
        "{'iata': '<código IATA 3 letras del aeropuerto principal de la ciudad>', "
        "'aeropuerto_nombre': '<nombre completo del aeropuerto, opcional>'}. "
        "Códigos IATA principales España: AGP (Málaga), MAD (Madrid-Barajas), "
        "BCN (Barcelona-El Prat), PMI (Palma de Mallorca), ALC (Alicante-Elche), "
        "SVQ (Sevilla), VLC (Valencia), BIO (Bilbao), SDR (Santander), ZAZ (Zaragoza), "
        "GRX (Granada), MXP (Murcia-Corvera), ACE (Lanzarote), TFS (Tenerife Sur)."
    ),
    "params_ejemplo": {"iata": "AGP", "aeropuerto_nombre": "Málaga-Costa del Sol"},
}
