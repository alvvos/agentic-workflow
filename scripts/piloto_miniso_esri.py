"""
Piloto Esri GeoEnrichment — organización Miniso España (3 localizaciones).

Uso:
    python scripts/piloto_miniso_esri.py

Efecto:
    - Llama a Esri Enrich por cada ubicación Miniso con RingBuffer 400/800/1200 m.
    - Ingesta los valores en geo_features.json con política de back-date automática.
    - Imprime un resumen de lo que se ha escrito.

Coste estimado: ~14 vars × 3 áreas × 3 locs = 126 atributos ≈ 0.13 USD
"""
import os
import sys
from pathlib import Path

# Permitir ejecución desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar .env antes de importar módulos que leen ESRI_KEY
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from src.data_ingestion.esri_client import cargar_todas_ubicaciones  # noqa: E402

if __name__ == "__main__":
    print("=" * 60)
    print("Piloto Esri — Miniso España")
    print("=" * 60)

    resultados = cargar_todas_ubicaciones(
        org_filter="Miniso",
        fecha_entrega="2026-05-27",
        dry_run=False,
    )

    print("\n" + "=" * 60)
    print(f"Total ubicaciones procesadas: {len(resultados)}")
    for r in resultados:
        print(f"\n  {r['name']} ({r['location_uuid'][:8]}…)")
        print(f"    Primera entrega: {r.get('primera_entrega')}")
        print(f"    Snapshots creados: {r.get('snapshots_creados')}")
        feats = r.get('features_registradas', [])
        print(f"    Features con valor ({len(feats)}): {', '.join(feats)}")
