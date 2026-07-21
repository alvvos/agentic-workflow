"""
Orquestador MCP — conecta el frontend Dash con Claude y las herramientas locales.

Flujo:
  1. Recibe historial de mensajes + contexto de ubicación activa.
  2. Llama a Claude claude-sonnet-4-6 con las tool definitions.
  3. Si Claude solicita una herramienta, la ejecuta en local (tools.py).
  4. Devuelve la respuesta final como string.
"""

import json
import os
from datetime import date

import anthropic

from src.chatbot.cache import get_cached, set_cached
from src.chatbot.tools import (
    _find_location,
    compare_locations,
    get_active_features,
    get_anomalies,
    get_cruise_calls,
    get_dwell_profile,
    get_external_features,
    get_forecast,
    get_funnel_ratios,
    get_gis_data,
    get_hourly_breakdown,
    get_location_info,
    get_model_metrics,
    get_pm_data,
    get_weather_holidays,
)

_MODEL = "claude-sonnet-4-6"

_TOOL_DEFINITIONS = [
    {
        "name": "get_weather_holidays",
        "description": (
            "Devuelve datos meteorológicos y festivos regionales para una ubicación "
            "en un rango de fechas: temperatura máx/mín diaria, precipitación y "
            "listado de festivos nacionales y autonómicos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_id": {"type": "string", "description": "UUID de la ubicación."},
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
            },
            "required": ["location_id", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_pm_data",
        "description": (
            "Obtiene métricas de tráfico de visitantes para una ubicación concreta "
            "en un rango de fechas: visitas totales, media diaria, hora pico, "
            "tiempo de permanencia, visitantes nuevos y comparativa WoW."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_id": {"type": "string", "description": "UUID de la ubicación."},
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
                "zone_uuid": {"type": "string", "description": "UUID de zona (opcional)."},
            },
            "required": ["location_id", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_forecast",
        "description": (
            "Ejecuta el modelo predictivo XGBoost y devuelve las visitas previstas "
            "para los próximos N días de una zona concreta. Incluye métricas de precisión "
            "(accuracy, MAE, WMAPE) si hay datos reales recientes con los que comparar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "zone_uuid": {"type": "string", "description": "UUID de la zona a predecir."},
                "n_dias": {
                    "type": "integer",
                    "description": "Horizonte de predicción en días (1-90). Default 14.",
                },
            },
            "required": ["location_uuid", "zone_uuid"],
        },
    },
    {
        "name": "get_anomalies",
        "description": (
            "Detecta días con tráfico anómalo (z-score > 2σ) en un rango de fechas. "
            "Devuelve picos y caídas ordenados por magnitud, con contexto de la media "
            "del periodo. Útil para identificar eventos, incidencias o patrones atípicos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
                "zone_uuid": {
                    "type": "string",
                    "description": "UUID de zona específica (opcional).",
                },
            },
            "required": ["location_uuid", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_hourly_breakdown",
        "description": (
            "Devuelve el perfil horario de visitas: hora pico global, y por cada día de la semana "
            "la hora pico y las visitas medias. Útil para responder preguntas sobre cuándo llega "
            "el mayor tráfico, diferencias entre días laborables y fin de semana, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
                "zone_uuid": {
                    "type": "string",
                    "description": "UUID de zona específica (opcional).",
                },
            },
            "required": ["location_uuid", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "compare_locations",
        "description": (
            "Compara métricas de tráfico entre dos o más ubicaciones en el mismo periodo. "
            "Devuelve totales, medias diarias y un ranking. Métricas disponibles: "
            "total_visits, unique_visitors, new_visitors, dwell_time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de UUIDs de ubicaciones a comparar.",
                },
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
                "metrica": {
                    "type": "string",
                    "description": "Métrica a comparar (default: unique_visitors).",
                },
            },
            "required": ["location_uuids", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_gis_data",
        "description": (
            "Devuelve el perfil geoespacial local de una ubicación: población accesible "
            "a 5/10/15 min a pie, renta del hogar, gasto en ropa, presión omnicanal, "
            "salud financiera del área y entorno competitivo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "fecha": {
                    "type": "string",
                    "description": "Fecha ISO para snapshot histórico (opcional).",
                },
            },
            "required": ["location_uuid"],
        },
    },
    {
        "name": "get_location_info",
        "description": (
            "Devuelve información completa de una ubicación: nombre, organización, "
            "dirección, ciudad, coordenadas y lista de todas sus zonas con sus UUIDs. "
            "Úsala cuando el usuario pregunte qué es o dónde está una ubicación, "
            "o para obtener los UUIDs de las zonas antes de llamar a otras herramientas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
            },
            "required": ["location_uuid"],
        },
    },
    {
        "name": "get_active_features",
        "description": (
            "Lista las features externas activas para una ubicación: turistas, pasajeros "
            "de crucero, viajeros de metro, clima, vacaciones escolares, etc. Muestra "
            "fuente, categoría, último valor registrado e impacto en el modelo predictivo. "
            "Úsala para responder qué datos de contexto externo tiene disponibles la ubicación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
            },
            "required": ["location_uuid"],
        },
    },
    {
        "name": "get_external_features",
        "description": (
            "Devuelve la serie temporal de features externas (turistas, pasajeros de crucero, "
            "viajeros de metro, temperatura, precipitación, etc.) en un rango de fechas. "
            "Incluye resumen estadístico (total, media, máximo) y comparativa YoY opcional. "
            "feature_keys disponibles típicos: n_turistas_ciudad, n_pasajeros_crucero_dia, "
            "n_viajeros_metro_estacion, temp_max, temp_min, llueve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "feature_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de feature keys a consultar.",
                },
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
                "incluir_yoy": {
                    "type": "boolean",
                    "description": "Si true, añade comparativa con el mismo periodo del año anterior.",
                },
            },
            "required": ["location_uuid", "feature_keys", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_cruise_calls",
        "description": (
            "Devuelve las escalas individuales de cruceros en una ubicación portuaria: "
            "nombre del barco, operador, número de pasajeros y terminal. "
            "Incluye resumen mensual de pasajeros y comparativa YoY con el año anterior. "
            "Solo disponible para ubicaciones con puerto de cruceros (ej: Málaga Muelle 1)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {
                    "type": "string",
                    "description": "UUID de la ubicación portuaria.",
                },
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
            },
            "required": ["location_uuid", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_model_metrics",
        "description": (
            "Devuelve las métricas de precisión del modelo predictivo XGBoost para una "
            "ubicación o zona: WMAPE, MAE, fecha de entrenamiento, features usadas y "
            "resultados de la evaluación individual de features. "
            "Úsala cuando el usuario pregunte sobre la precisión del modelo, qué features "
            "mejoran las predicciones o cuándo se entrenó el modelo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "zone_uuid": {
                    "type": "string",
                    "description": "UUID de la zona específica (opcional).",
                },
            },
            "required": ["location_uuid"],
        },
    },
    {
        "name": "get_funnel_ratios",
        "description": (
            "Calcula los ratios de conversión del embudo Exterior→Interior→Checkout "
            "(Calle→Tienda→Caja) para una ubicación en un rango de fechas. "
            "Devuelve visitantes por tipo de zona, ratio Calle→Tienda (%), ratio "
            "Tienda→Caja (%) y ratio global Calle→Caja (%), con comparativa WoW "
            "(mismos días semana anterior) y diferencia en puntos porcentuales. "
            "Úsala cuando el usuario pregunte sobre conversión, ratio de acceso a tienda, "
            "efectividad del embudo, cuántos que pasan por calle entran a la tienda, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
            },
            "required": ["location_uuid", "fecha_inicio", "fecha_fin"],
        },
    },
    {
        "name": "get_dwell_profile",
        "description": (
            "Devuelve el perfil de permanencia (dwell time) de visitantes para una "
            "ubicación/zona: media de estancia en minutos, distribución percentil "
            "(boxplot min/Q1/mediana/Q3/max) y fidelización por ventana temporal "
            "(7d, 28d, mes, año) con porcentaje de clientes que repiten visita. "
            "Úsala cuando el usuario pregunte cuánto tiempo pasan los clientes, "
            "tasa de fidelización, porcentaje de recurrentes o si los clientes vuelven."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_uuid": {"type": "string", "description": "UUID de la ubicación."},
                "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD."},
                "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD."},
                "zone_uuid": {
                    "type": "string",
                    "description": "UUID de la zona específica (opcional).",
                },
            },
            "required": ["location_uuid", "fecha_inicio", "fecha_fin"],
        },
    },
]

_TOOL_FN = {
    "get_pm_data": lambda args: get_pm_data(**args),
    "get_gis_data": lambda args: get_gis_data(**args),
    "get_weather_holidays": lambda args: get_weather_holidays(**args),
    "get_forecast": lambda args: get_forecast(**args),
    "get_anomalies": lambda args: get_anomalies(**args),
    "get_hourly_breakdown": lambda args: get_hourly_breakdown(**args),
    "compare_locations": lambda args: compare_locations(**args),
    "get_location_info": lambda args: get_location_info(**args),
    "get_active_features": lambda args: get_active_features(**args),
    "get_external_features": lambda args: get_external_features(**args),
    "get_cruise_calls": lambda args: get_cruise_calls(**args),
    "get_model_metrics": lambda args: get_model_metrics(**args),
    "get_funnel_ratios": lambda args: get_funnel_ratios(**args),
    "get_dwell_profile": lambda args: get_dwell_profile(**args),
}


def _system_prompt(
    location_uuid: str | None,
    zone_uuid: str | None = None,
    extra_mentions: list | None = None,
) -> str:
    today = date.today().isoformat()
    base = (
        f"Hoy es {today}. "
        "Eres el asistente analítico del panel de Project Management (PM Dashboard). "
        "Tienes acceso a datos reales de tráfico de visitantes, datos geoespaciales, "
        "clima, escalas de cruceros, features externas (cruceros, Esri), "
        "métricas del modelo predictivo e información de ubicaciones. "
        "Responde siempre en español, de forma concisa y orientada a decisiones de negocio. "
        "Si necesitas datos para responder, usa las herramientas disponibles. "
        "No inventes cifras; si no tienes datos, dilo claramente. "
        "Cuando el usuario mencione 'esta semana', 'el mes pasado' u otras referencias temporales, "
        "calcula las fechas exactas a partir de la fecha de hoy. "
        "Límite de consulta: máximo 90 días por llamada; si necesitas más, divide en varias llamadas. "
        "Formato: Markdown limpio — usa listas y negrita solo cuando aporten claridad. "
        "Sin emojis. Primera letra de cada oración en mayúscula; resto en minúsculas salvo nombres propios. "
        "Respuestas directas, sin frases de relleno ni introducciones genéricas. "
        "Responde únicamente lo que se pregunta. "
        "No añadas datos adicionales, contexto no solicitado ni secciones extra. "
        "Si la pregunta tiene una respuesta de una línea, una línea es suficiente. "
        "CRÍTICO: nunca pidas al usuario UUIDs, location_id ni identificadores técnicos. "
        "Todos los UUIDs necesarios están en este system prompt; úsalos directamente sin preguntar."
    )

    def _loc_block(loc_uuid: str, z_uuid: str | None = None, is_active: bool = False) -> str:
        loc = _find_location(loc_uuid)
        if not loc:
            return ""
        zones = [z for z in loc.get("zones", []) if not z.get("oculta")]
        zones_txt = (
            ", ".join(f"{z['zoneName']} (uuid: {z['uuid']})" for z in zones) or "sin zonas visibles"
        )
        label = "Ubicación activa" if is_active else "Ubicación mencionada"
        txt = (
            f"{label}: '{loc.get('name')}' ({loc.get('org', '')}). "
            f"UUID: {loc_uuid}. Zonas: {zones_txt}."
        )
        if z_uuid:
            zone_name = next((z["zoneName"] for z in zones if z["uuid"] == z_uuid), z_uuid)
            txt += f" Zona seleccionada: '{zone_name}' (uuid: {z_uuid})."
        return txt

    blocks: list[str] = []

    if location_uuid:
        block = _loc_block(location_uuid, zone_uuid, is_active=True)
        if block:
            blocks.append(block)

    if extra_mentions:
        seen = {location_uuid}
        for m in extra_mentions:
            uid = m.get("location_uuid")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            block = _loc_block(uid, m.get("zone_uuid"), is_active=False)
            if block:
                blocks.append(block)

    if blocks:
        base += "\n\n" + "\n".join(blocks)

    return base


def chat(
    messages: list[dict],
    location_uuid: str | None = None,
    session_id: str = "local_dev",
    max_turns: int = 5,
) -> str:
    """
    Ejecuta una conversación con Claude usando las herramientas locales.

    Args:
        messages:       Historial [{role, content},...] en formato Anthropic.
        location_uuid:  UUID de la ubicación activa en el panel (contexto).
        session_id:     ID de sesión para encontrar el CSV correcto.
        max_turns:      Límite de rondas tool_use→tool_result.

    Returns:
        Texto de la respuesta final de Claude.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "⚠ Configura ANTHROPIC_API_KEY en el entorno para activar el asistente."

    # Comprobar caché antes de llamar a la API
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    cached = get_cached(last_user, location_uuid)
    if cached:
        return f"⚡ {cached}"

    client = anthropic.Anthropic(api_key=api_key)
    history = list(messages)

    for _ in range(max_turns):
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_system_prompt(location_uuid),
            tools=_TOOL_DEFINITIONS,
            messages=history,
        )

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            answer = "\n".join(text_blocks).strip()
            set_cached(last_user, location_uuid, answer)
            return answer

        if response.stop_reason == "tool_use":
            # Añadir respuesta del asistente al historial
            history.append({"role": "assistant", "content": response.content})

            # Ejecutar cada tool_use y recoger resultados
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                fn = _TOOL_FN.get(block.name)
                args = {**block.input}
                _TOOLS_SESSION = {
                    "get_pm_data",
                    "get_forecast",
                    "get_anomalies",
                    "get_hourly_breakdown",
                    "compare_locations",
                }
                if block.name in _TOOLS_SESSION:
                    args.setdefault("session_id", session_id)

                result = fn(args) if fn else {"error": f"Herramienta desconocida: {block.name}"}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            history.append({"role": "user", "content": tool_results})
            continue

        # stop_reason inesperado
        break

    return "No se pudo generar una respuesta. Intenta reformular la pregunta."
