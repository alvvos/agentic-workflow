"""
Agente 3 — Context Scout.

Recibe un location_uuid que pasó Quality Gate + Feature Router.
Evalúa un catálogo curado de fuentes de datos abiertas, decide cuáles aplican
para la isócrona de esa ubicación y las registra en feature_registry + feature_flags
con status='contexto' y la periodicidad correspondiente.

Los timers de ingesta (sync_mensual.py) recogen automáticamente las nuevas filas
cuando el ingestor de esa source esté disponible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic

log = logging.getLogger(__name__)

# ── Catálogo curado por país ───────────────────────────────────────────────────
# Solo fuentes con API o descarga CSV programática, cobertura desde ≤2024,
# actualización mensual o trimestral, y mecanismo causal documentado.
# Añadir nuevos países o fuentes aquí — context_scout los evaluará automáticamente.

_CATALOG: dict[str, list[dict]] = {
    "ES": [
        {
            "feature_key_template": "ine_icm_minorista_{provincia_snake}",
            "source": "ine",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "Índice de Comercio Minorista — INE. Mide la evolución del volumen de "
                "negocio del comercio al por menor a precios constantes. "
                "Disponible por CCAA y provincia."
            ),
            "url_referencia": "https://www.ine.es/dyngs/IOE/es/operacion.htm?numinv=30250",
            "url_descarga": "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/2688?tip=AM",
            "granularidad": "provincial",
            "cobertura_desde": "2001-01",
            "latencia_dias": 45,
            "notas_tecnicas": (
                "Publicado ~6 semanas después del mes de referencia. "
                "Usar la serie IRA (índice ajustado estacionalmente) para eliminar "
                "efecto calendario. Formato JSON via API INE sin autenticación."
            ),
        },
        {
            "feature_key_template": "sepe_paro_registrado_{municipio_snake}",
            "source": "sepe",
            "categoria": "laboral",
            "periodicidad": "mensual",
            "descripcion": (
                "Paro registrado por municipio — SEPE. Número de personas desempleadas "
                "inscritas en oficinas de empleo el último día hábil de cada mes."
            ),
            "url_referencia": "https://www.sepe.es/HomeSepe/que-es-el-sepe/estadisticas/datos-estadisticos/paro/datos-municipios.html",
            "url_descarga": "https://www.sepe.es/HomeSepe/que-es-el-sepe/estadisticas/datos-estadisticos/paro/datos-municipios.html",
            "granularidad": "municipal",
            "cobertura_desde": "2006-01",
            "latencia_dias": 10,
            "notas_tecnicas": (
                "Disponible como Excel/CSV por municipio. Actualizado el día 10 de "
                "cada mes. Dato absoluto — normalizar por población activa del municipio "
                "para comparabilidad entre ubicaciones."
            ),
        },
        {
            "feature_key_template": "ine_ipc_ccaa_{ccaa_snake}",
            "source": "ine",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "IPC General por CCAA — INE. Variación del nivel de precios al consumo. "
                "Proxy del poder adquisitivo regional."
            ),
            "url_referencia": "https://www.ine.es/dyngs/IOE/es/operacion.htm?numinv=30138",
            "url_descarga": "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/50902?tip=AM",
            "granularidad": "ccaa",
            "cobertura_desde": "2002-01",
            "latencia_dias": 30,
            "notas_tecnicas": (
                "Disponible a nivel CCAA, no provincial. Usar como proxy regional. "
                "Latencia ~30 días. API INE sin autenticación."
            ),
        },
        {
            "feature_key_template": "ine_turismo_hotelero_{provincia_snake}",
            "source": "ine",
            "categoria": "turismo",
            "periodicidad": "mensual",
            "descripcion": (
                "Encuesta de Ocupación Hotelera — INE. Viajeros y pernoctaciones por "
                "provincia y tipo de establecimiento."
            ),
            "url_referencia": "https://www.ine.es/dyngs/IOE/es/operacion.htm?numinv=23692",
            "url_descarga": "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/2074?tip=AM",
            "granularidad": "provincial",
            "cobertura_desde": "1999-01",
            "latencia_dias": 45,
            "notas_tecnicas": (
                "Solo relevante para provincias con peso turístico significativo "
                "(costera, capital, Patrimonio UNESCO). Evaluar si la ubicación "
                "está en zona de influencia turística antes de incluir."
            ),
        },
    ],
    "MX": [
        {
            "feature_key_template": "inegi_igae_mensual",
            "source": "inegi",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "Indicador Global de la Actividad Económica — INEGI. "
                "Aproximación mensual del PIB. Ciclo económico nacional."
            ),
            "url_referencia": "https://www.inegi.org.mx/temas/igae/",
            "url_descarga": "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/628193/es/0700/false/BIE/2.0/{token}?type=json",
            "granularidad": "nacional",
            "cobertura_desde": "2008-01",
            "latencia_dias": 50,
            "notas_tecnicas": (
                "Dato nacional — no hay desagregación estatal en esta serie. "
                "Requiere token INEGI gratuito (registro en inegi.org.mx)."
            ),
        },
        {
            "feature_key_template": "banxico_enco_confianza_consumidor",
            "source": "banxico_inegi",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "Encuesta Nacional sobre Confianza del Consumidor — Banxico/INEGI. "
                "Percepciones sobre situación económica del hogar y del país."
            ),
            "url_referencia": "https://www.inegi.org.mx/temas/enco/",
            "url_descarga": "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/370958/es/0700/false/BIE/2.0/{token}?type=json",
            "granularidad": "nacional",
            "cobertura_desde": "2001-01",
            "latencia_dias": 30,
            "notas_tecnicas": "Requiere token INEGI gratuito. Solo a nivel nacional.",
        },
        {
            "feature_key_template": "inegi_desocupacion_trimestral_{entidad_snake}",
            "source": "inegi",
            "categoria": "laboral",
            "periodicidad": "trimestral",
            "descripcion": (
                "Tasa de Desocupación por entidad federativa — INEGI ENOE. "
                "Porcentaje de la PEA sin empleo."
            ),
            "url_referencia": "https://www.inegi.org.mx/temas/empleo/",
            "url_descarga": "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/444649/es/0700/false/BIE/2.0/{token}?type=json",
            "granularidad": "estatal",
            "cobertura_desde": "2005-Q1",
            "latencia_dias": 60,
            "notas_tecnicas": (
                "Publicada trimestralmente (~60 días después del trimestre). "
                "Disponible a nivel estatal. Requiere token INEGI."
            ),
        },
    ],
    "FR": [
        {
            "feature_key_template": "insee_icc_confianza_consumidor",
            "source": "insee",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "Indicateur de confiance des ménages — INSEE. "
                "Índice de confianza del consumidor francés."
            ),
            "url_referencia": "https://www.insee.fr/fr/statistiques/series/102539611",
            "url_descarga": "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/001762583",
            "granularidad": "nacional",
            "cobertura_desde": "1987-01",
            "latencia_dias": 30,
            "notas_tecnicas": "Requiere token INSEE API (gratuito). Solo dato nacional.",
        },
        {
            "feature_key_template": "dares_chomage_localise_{departement_snake}",
            "source": "dares",
            "categoria": "laboral",
            "periodicidad": "trimestral",
            "descripcion": (
                "Taux de chômage localisé par département — DARES/INSEE. "
                "Tasa de desempleo por departamento."
            ),
            "url_referencia": "https://www.insee.fr/fr/statistiques/1893230",
            "url_descarga": "https://www.insee.fr/fr/statistiques/fichier/1893230/chomage-localise-departements-regions.xlsx",
            "granularidad": "departamento",
            "cobertura_desde": "2003-Q1",
            "latencia_dias": 90,
            "notas_tecnicas": "Trimestral. Descarga Excel directa sin autenticación.",
        },
    ],
    "DE": [
        {
            "feature_key_template": "destatis_einzelhandel_umsatz",
            "source": "destatis",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "Umsatz im Einzelhandel — Destatis. Ventas al por menor en Alemania "
                "a precios constantes. Indicador líder del consumo privado."
            ),
            "url_referencia": "https://www.destatis.de/EN/Themes/Economy/Short-Term-Indicators/Trade-Services/ghd110.html",
            "url_descarga": "https://www-genesis.destatis.de/genesis/online?operation=abruftabelleBearbeiten&levelindex=0&code=45212-0009",
            "granularidad": "nacional",
            "cobertura_desde": "2000-01",
            "latencia_dias": 35,
            "notas_tecnicas": (
                "API Genesis Destatis (registro gratuito). Dato nacional con "
                "desagregación por tipo de establecimiento (alimentación, textil, etc.)."
            ),
        },
        {
            "feature_key_template": "ba_arbeitslosigkeit_{kreis_snake}",
            "source": "bundesagentur_arbeit",
            "categoria": "laboral",
            "periodicidad": "mensual",
            "descripcion": (
                "Arbeitslosenzahlen nach Kreisen — Bundesagentur für Arbeit. "
                "Desempleo registrado por distrito (Kreis)."
            ),
            "url_referencia": "https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html",
            "url_descarga": "https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html",
            "granularidad": "kreis",
            "cobertura_desde": "2005-01",
            "latencia_dias": 30,
            "notas_tecnicas": (
                "Granularidad a nivel Kreis (distrito). Descarga CSV/Excel. "
                "Actualizado el día ~20 de cada mes."
            ),
        },
    ],
    "GB": [
        {
            "feature_key_template": "ons_retail_sales_index",
            "source": "ons",
            "categoria": "macroeconomia",
            "periodicidad": "mensual",
            "descripcion": (
                "Retail Sales Index — ONS. Volumen y valor de las ventas al por menor "
                "en Gran Bretaña por tipo de establecimiento."
            ),
            "url_referencia": "https://www.ons.gov.uk/businessindustryandtrade/retailindustry/bulletins/retailsales",
            "url_descarga": "https://api.ons.gov.uk/v1/datasets/retail-sales-index/timeseries/J5EK/data",
            "granularidad": "nacional",
            "cobertura_desde": "1988-01",
            "latencia_dias": 30,
            "notas_tecnicas": "API ONS pública sin autenticación. Respuesta JSON.",
        },
        {
            "feature_key_template": "ons_claimant_count_{local_authority_snake}",
            "source": "ons",
            "categoria": "laboral",
            "periodicidad": "mensual",
            "descripcion": (
                "Claimant Count por Local Authority District — ONS. "
                "Personas que cobran prestación por desempleo, a nivel LAD."
            ),
            "url_referencia": "https://www.ons.gov.uk/employmentandlabourmarket/peoplenotinwork/unemployment/datasets/claimantcountbyladistrict",
            "url_descarga": "https://www.ons.gov.uk/generator?format=csv&uri=/employmentandlabourmarket/peoplenotinwork/unemployment/datasets/claimantcountbyladistrict",
            "granularidad": "local_authority",
            "cobertura_desde": "2013-01",
            "latencia_dias": 30,
            "notas_tecnicas": "CSV directo sin autenticación. Granularidad LAD.",
        },
    ],
}

# ── Sources ya cubiertas por el sistema — el Scout nunca las duplica ───────────
_FUENTES_EXCLUIDAS = {
    "open_meteo": "clima histórico y forecast (temp_max, temp_min, llueve)",
    "supercalendario": "festivos, calendarios escolares y laborales por org",
    "cruceros": "escalas Puerto Málaga (n_pasajeros_crucero_dia)",
    "predicthq": "eventos Ticketmaster/PredictHQ (evaluado, sin cobertura histórica en tier gratuito)",
    "esri": "enriquecimiento geoespacial Esri (pendiente contrato)",
    "academic_calendar": "calendario académico (incluido en supercalendario)",
}

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Eres un analista de datos senior especializado en señales contextuales para modelos \
de forecasting de afluencia en retail físico.

Tu único objetivo en esta tarea es evaluar un catálogo de fuentes de datos abiertas \
y determinar cuáles aportan señal causal válida para una ubicación comercial concreta, \
teniendo en cuenta su isócrona, país, ciudad y tipología urbana.

No estás aquí para ser exhaustivo ni creativo — estás aquí para ser preciso y conservador. \
Prefiero 3 fuentes sólidas a 8 cuestionables.

━━━ SISTEMA PARA EL QUE TRABAJAS ━━━

El sistema gestiona un modelo XGBoost de predicción de visitas diarias para tiendas físicas. \
El modelo entrena sobre series temporales de afluencia y consume features externas para reducir \
el WMAPE (error de predicción normalizado). Las features se almacenan en store_features_ext \
como series diarias por (fecha, location_uuid, feature_key).

El pipeline de vida de una feature nueva es:
  1. Registro en feature_registry con status='incompleto'
  2. Un ingestor mensual descarga los datos históricos → store_features_ext
  3. _promote_if_covered() verifica cobertura diaria completa → status='con_cobertura'
  4. Evaluación walk-forward WMAPE (wmape_delta < 0 = mejora)
  5. Si mejora: feature_flags.status='active' → entra al modelo

Las features que registres en esta tarea entrarán como status='contexto': \
visibles en el panel de Señal de Contexto del dashboard, pero fuera del modelo \
hasta que se evalúe su impacto en WMAPE. El valor de registrarlas es que el timer \
mensual las irá alimentando desde el primer día, para que cuando llegue la evaluación \
ya haya histórico.

━━━ FUENTES YA INTEGRADAS — NO DUPLICAR ━━━

{exclusion_block}

━━━ UBICACIÓN A ANALIZAR ━━━

{location_block}

━━━ CATÁLOGO A EVALUAR ━━━

Para cada fuente del siguiente catálogo, decide si aplica a esta ubicación específica \
siguiendo los criterios de evaluación que encontrarás al final.

{catalog_block}

━━━ CRITERIOS DE EVALUACIÓN ━━━

Incluye una fuente SOLO si cumple todos estos requisitos:

1. GRANULARIDAD ADECUADA: El dato existe a nivel de municipio, provincia, departamento \
   o región de la ubicación. Si solo existe a nivel nacional, puedes incluirlo siempre \
   que documentes esa limitación en 'notas' y el constructo sea relevante.

2. COBERTURA HISTÓRICA: Tiene datos accesibles desde al menos enero de 2024 \
   (preferiblemente desde 2022 o antes para permitir evaluaciones walk-forward amplias).

3. FRECUENCIA MÍNIMA: Actualización mensual. Datos trimestrales solo si no existe \
   alternativa mensual para el mismo constructo económico.

4. ACCESO PROGRAMÁTICO: Descargable vía API REST, endpoint CSV o similar. \
   Excluye fuentes que solo publican en PDF, en interfaces web de solo lectura \
   o que requieren scraping frágil.

5. MECANISMO CAUSAL DOCUMENTADO: Existe un mecanismo plausible y específico por el \
   que esta variable explica variaciones en afluencia peatonal en esta ubicación concreta. \
   "Es una medida de la economía" no es suficiente. "El ICM provincial mide directamente \
   el volumen de ventas en comercio minorista — cuando cae, la gente va menos a centros \
   comerciales de la misma provincia" sí lo es.

6. NO REDUNDANCIA: No mide el mismo constructo que una fuente ya excluida o ya incluida \
   en tu respuesta. Si dos fuentes miden lo mismo, elige la de mayor granularidad geográfica \
   o menor latencia.

SESGO CONSERVADOR: Ante la duda entre incluir y excluir, excluye. \
Documenta el motivo en 'fuentes_descartadas' para que el equipo pueda revisarlo.

━━━ FORMATO DE RESPUESTA ━━━

Responde ÚNICAMENTE con JSON válido. Sin markdown, sin texto antes ni después del JSON.

{{
  "fuentes_seleccionadas": [
    {{
      "feature_key": "ine_icm_minorista_zaragoza",
      "source": "ine",
      "categoria": "macroeconomia",
      "periodicidad": "mensual",
      "url": "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/2688?tip=AM",
      "notas": "Índice de Comercio Minorista INE a nivel provincial (Zaragoza). Mide directamente el volumen de ventas en comercio al por menor. Publicado ~45 días después del mes de referencia. Usar serie IRA (ajustada estacionalmente). API JSON sin autenticación.",
      "razon_inclusion": "Zaragoza tiene dato ICM provincial propio. Alta correlación esperada con afluencia en retail — cuando el índice cae, el gasto en tiendas físicas de la provincia cae con él."
    }}
  ],
  "fuentes_descartadas": [
    {{
      "feature_key": "ine_turismo_hotelero_zaragoza",
      "razon_descarte": "Zaragoza no es destino turístico de primer orden. La ocupación hotelera no está causalmente vinculada a la afluencia en retail de conveniencia/moda en esta ciudad."
    }}
  ]
}}
"""


# ── Dataclass de resultado ─────────────────────────────────────────────────────


@dataclass
class ContextSource:
    feature_key: str
    source: str
    categoria: str
    periodicidad: str
    url: str
    notas: str
    razon_inclusion: str


@dataclass
class ScoutResult:
    location_uuid: str
    nombre: str
    seleccionadas: list[ContextSource] = field(default_factory=list)
    descartadas: list[dict] = field(default_factory=list)
    n_registradas: int = 0
    error: str | None = None


# ── Helpers de construcción de prompt ─────────────────────────────────────────


def _build_exclusion_block() -> str:
    lines = []
    for source, desc in _FUENTES_EXCLUIDAS.items():
        lines.append(f"  - {source}: {desc}")
    return "\n".join(lines)


def _build_location_block(row: tuple) -> str:
    nombre, ciudad, provincia, pais_codigo, lat, lon, codigo_postal, direccion = row
    return (
        f"  nombre:         {nombre}\n"
        f"  ciudad:         {ciudad}\n"
        f"  provincia:      {provincia or '(desconocida)'}\n"
        f"  pais_codigo:    {pais_codigo}\n"
        f"  coordenadas:    {lat}, {lon}\n"
        f"  codigo_postal:  {codigo_postal or '(desconocido)'}\n"
        f"  direccion:      {direccion or '(desconocida)'}\n"
        f"\n"
        f"  Isócrona de referencia: radio peatonal ~10 min (~800 m), radio coche ~15 min.\n"
        f"  Tipología: tienda física en entorno urbano — afluencia determinada por "
        f"consumo local, empleo, eventos y dinámica comercial del área."
    )


def _build_catalog_block(pais: str) -> str:
    entries = _CATALOG.get(pais, [])
    if not entries:
        return f"  (No hay fuentes curadas para pais_codigo='{pais}'. Responde con listas vacías.)"
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(f"\n  [{i}] {e['feature_key_template']}")
        lines.append(f"      source:       {e['source']}")
        lines.append(f"      categoria:    {e['categoria']}")
        lines.append(f"      periodicidad: {e['periodicidad']}")
        lines.append(f"      granularidad: {e['granularidad']}")
        lines.append(
            f"      cobertura:    desde {e['cobertura_desde']}, latencia ~{e['latencia_dias']}d"
        )
        lines.append(f"      descripcion:  {e['descripcion']}")
        lines.append(f"      notas_tecn.:  {e['notas_tecnicas']}")
        lines.append(f"      url_descarga: {e['url_descarga']}")
    return "\n".join(lines)


# ── Función principal ──────────────────────────────────────────────────────────


def descubrir_fuentes(location_uuid: str) -> ScoutResult:
    """
    Evalúa el catálogo de fuentes para la ubicación y devuelve un ScoutResult.
    No escribe a DB — eso lo hace registrar_fuentes().
    """
    from src.db.store import get_conn

    conn = get_conn()
    row = conn.execute(
        """
        SELECT nombre, ciudad, provincia, pais_codigo, lat, lon, codigo_postal, direccion
        FROM dim_ubicaciones
        WHERE location_uuid = ?
        """,
        [location_uuid],
    ).fetchone()

    if not row:
        return ScoutResult(
            location_uuid=location_uuid,
            nombre="?",
            error=f"location_uuid '{location_uuid}' no encontrado en dim_ubicaciones",
        )

    pais = (row[3] or "").upper()
    nombre = row[0] or location_uuid

    if pais not in _CATALOG:
        log.info("Context Scout: pais_codigo='%s' sin catálogo curado — omitiendo", pais)
        return ScoutResult(location_uuid=location_uuid, nombre=nombre)

    prompt = _SYSTEM_PROMPT.format(
        exclusion_block=_build_exclusion_block(),
        location_block=_build_location_block(row),
        catalog_block=_build_catalog_block(pais),
    )

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ScoutResult(
            location_uuid=location_uuid,
            nombre=nombre,
            error=f"Claude devolvió JSON inválido: {exc}",
        )
    except Exception as exc:
        return ScoutResult(
            location_uuid=location_uuid,
            nombre=nombre,
            error=f"Error llamando a Anthropic API: {exc}",
        )

    seleccionadas = [
        ContextSource(
            feature_key=s["feature_key"],
            source=s["source"],
            categoria=s.get("categoria", "macroeconomia"),
            periodicidad=s.get("periodicidad", "mensual"),
            url=s.get("url", ""),
            notas=s.get("notas", ""),
            razon_inclusion=s.get("razon_inclusion", ""),
        )
        for s in data.get("fuentes_seleccionadas", [])
    ]

    return ScoutResult(
        location_uuid=location_uuid,
        nombre=nombre,
        seleccionadas=seleccionadas,
        descartadas=data.get("fuentes_descartadas", []),
    )


def registrar_fuentes(result: ScoutResult) -> ScoutResult:
    """
    Escribe en feature_registry + feature_flags las fuentes seleccionadas.
    Idempotente: si feature_key ya existe, no duplica.
    Devuelve el mismo ScoutResult con n_registradas actualizado.
    """
    if not result.seleccionadas or result.error:
        return result

    from src.db.store import get_conn

    conn = get_conn()
    ahora = datetime.now(timezone.utc)
    n = 0

    for src in result.seleccionadas:
        # feature_registry — upsert
        existing = conn.execute(
            "SELECT feature_key FROM feature_registry WHERE feature_key = ?",
            [src.feature_key],
        ).fetchone()

        if not existing:
            notas_completas = src.notas
            if src.razon_inclusion:
                notas_completas += (
                    f"\n\nRazón de inclusión para {result.nombre}: {src.razon_inclusion}"
                )

            conn.execute(
                """
                INSERT INTO feature_registry
                  (feature_key, source, categoria, org_applicability,
                   location_applicability, status, notas, registrado_en)
                VALUES (?, ?, ?, ?, ?, 'incompleto', ?, ?)
                """,
                [
                    src.feature_key,
                    src.source,
                    src.categoria,
                    json.dumps("all"),
                    json.dumps([result.location_uuid]),
                    notas_completas,
                    ahora,
                ],
            )
            log.info("feature_registry INSERT: %s", src.feature_key)
        else:
            # La feature ya existe — solo ampliar location_applicability si es necesario
            loc_row = conn.execute(
                "SELECT location_applicability FROM feature_registry WHERE feature_key = ?",
                [src.feature_key],
            ).fetchone()
            if loc_row and loc_row[0]:
                try:
                    existing_locs = json.loads(loc_row[0])
                    if (
                        isinstance(existing_locs, list)
                        and result.location_uuid not in existing_locs
                    ):
                        existing_locs.append(result.location_uuid)
                        conn.execute(
                            "UPDATE feature_registry SET location_applicability = ? WHERE feature_key = ?",
                            [json.dumps(existing_locs), src.feature_key],
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

        # feature_flags — solo si no existe ya para esta (feature, location)
        flag_exists = conn.execute(
            "SELECT 1 FROM feature_flags WHERE feature_key = ? AND location_uuid = ?",
            [src.feature_key, result.location_uuid],
        ).fetchone()

        if not flag_exists:
            conn.execute(
                """
                INSERT INTO feature_flags
                  (feature_key, location_uuid, status, periodicidad)
                VALUES (?, ?, 'contexto', ?)
                """,
                [src.feature_key, result.location_uuid, src.periodicidad],
            )
            log.info(
                "feature_flags INSERT: %s / %s — contexto/%s",
                src.feature_key,
                result.location_uuid,
                src.periodicidad,
            )
            n += 1

    result.n_registradas = n
    return result
