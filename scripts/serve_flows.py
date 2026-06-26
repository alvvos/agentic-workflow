"""
Registra y sirve todos los flows de Prefect.

Mantiene un proceso vivo que escucha el API de Prefect y ejecuta
los flows cuando se disparan (desde sync, desde la UI o por schedule).

Uso:
    python scripts/serve_flows.py

En producción lo gestiona systemd (prefect-flows.service).
La UI de Prefect está en http://localhost:4200 (acceder vía SSH tunnel).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ para importar siblings

from prefect import serve
from sync_mensual import sync_mensual_flow

from src.onboarding.pipeline import onboard_nuevas_ubicaciones, onboarding_ubicacion

if __name__ == "__main__":
    serve(
        onboarding_ubicacion.to_deployment(
            name="onboarding-ubicacion-manual",
            description="Lanzamiento manual de onboarding para una ubicación concreta",
        ),
        onboard_nuevas_ubicaciones.to_deployment(
            name="onboarding-lote-trigger",
            description="Disparado automáticamente por descargar_maestro_ubicaciones()",
        ),
        sync_mensual_flow.to_deployment(
            name="sync-mensual-timer",
            description="Ingesta mensual data-driven: cruceros + fuentes Context Scout + audit geo",
        ),
    )
