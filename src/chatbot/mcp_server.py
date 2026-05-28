"""
Servidor MCP independiente — expone get_pm_data y get_gis_data vía stdio.

Uso (desarrollo / testing con cualquier cliente MCP):
    python -m src.chatbot.mcp_server

El servidor Dash NO arranca este proceso directamente; usa tools.py de forma
in-process para evitar conflictos con gunicorn multi-worker.
"""
from mcp.server.fastmcp import FastMCP

from src.chatbot.tools import get_pm_data as _get_pm_data
from src.chatbot.tools import get_gis_data as _get_gis_data

mcp = FastMCP(
    name="pm-dashboard",
    instructions=(
        "Eres el asistente del panel de Project Management. "
        "Tienes acceso a datos de tráfico de visitantes y datos geoespaciales "
        "de las ubicaciones de los clientes. Responde siempre en español, "
        "de forma concisa y orientada a decisiones de negocio."
    ),
)


@mcp.tool()
def get_pm_data(
    location_id: str,
    fecha_inicio: str,
    fecha_fin: str,
    zone_uuid: str = "",
) -> dict:
    """
    Devuelve métricas de tráfico de una ubicación en un rango de fechas.

    Args:
        location_id:   UUID de la ubicación (location).
        fecha_inicio:  Fecha de inicio en formato YYYY-MM-DD.
        fecha_fin:     Fecha de fin en formato YYYY-MM-DD.
        zone_uuid:     UUID de zona específica (opcional, vacío = todas las zonas).
    """
    return _get_pm_data(
        location_id=location_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        zone_uuid=zone_uuid or None,
    )


@mcp.tool()
def get_gis_data(
    location_uuid: str,
    fecha: str = "",
) -> dict:
    """
    Devuelve datos geoespaciales almacenados localmente para una ubicación.

    Args:
        location_uuid: UUID de la ubicación.
        fecha:         Fecha ISO para snapshot histórico (vacío = snapshot activo).
    """
    return _get_gis_data(
        location_uuid=location_uuid,
        fecha=fecha or None,
    )


if __name__ == "__main__":
    mcp.run()
