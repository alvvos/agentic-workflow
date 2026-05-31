"""
Enriquecimiento Esri con selección de ubicaciones y previsualización de coste.

Uso:
    python scripts/enriquecer_esri.py                      # muestra menú interactivo de orgs
    python scripts/enriquecer_esri.py --org "Miniso"       # filtro por nombre de org
    python scripts/enriquecer_esri.py --org "Miniso" "Barceló"  # varias orgs
    python scripts/enriquecer_esri.py --all                # todas las ubicaciones
    python scripts/enriquecer_esri.py --dry-run            # solo previsualizar, nunca ejecutar
    python scripts/enriquecer_esri.py --force              # re-enriquecer aunque ya haya datos de hoy
    python scripts/enriquecer_esri.py --fecha 2026-06-15   # fecha de entrega personalizada

Opciones combinables:
    python scripts/enriquecer_esri.py --org "Miniso" --dry-run
    python scripts/enriquecer_esri.py --all --force --fecha 2026-06-01
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from src.data_processing.geo_enrichment import ESRI_VAR_MAP, GEO_FEATURE_COLS  # noqa: E402

_UBIC_PATH = Path(__file__).parent.parent / "src" / "data" / "todas_las_ubicaciones.json"
_GEO_PATH  = Path(__file__).parent.parent / "src" / "data" / "geo_features.json"

# Billing: Esri cobra por variable única × áreas. PEOPLE aparece 3 veces en ESRI_VAR_MAP
# (una por cada ring index) pero en analysisVariables solo se envía una vez (dedup).
_UNIQUE_VARS = len({var_id for _, entry in ESRI_VAR_MAP.items()
                    if entry is not None for var_id, _ in [entry]})
_RINGS        = 3   # bufferRadii=[400, 800, 1200]
_USD_PER_1000 = 1.0  # precio estándar Esri; verificar en pricing page para EUR


def _cargar_todas() -> list[dict]:
    with open(_UBIC_PATH, encoding="utf-8") as f:
        return json.load(f)


def _cargar_geo_store() -> dict:
    if not _GEO_PATH.exists():
        return {}
    with open(_GEO_PATH, encoding="utf-8") as f:
        return json.load(f)


def _ya_enriquecida_hoy(location_uuid: str, store: dict, fecha_entrega: str) -> bool:
    """True si ya existe un snapshot con valid_from == fecha_entrega para esta ubicación."""
    snaps = store.get(location_uuid, [])
    return any(
        s.get("valid_from") == fecha_entrega and
        any(s.get(c) is not None for c in GEO_FEATURE_COLS)
        for s in snaps
        if isinstance(s, dict)
    )


def _seleccionar_ubicaciones_interactivo(orgs: list[dict]) -> list[dict]:
    """Muestra menú de organizaciones y devuelve las ubicaciones seleccionadas."""
    print("\nOrganizaciones disponibles:")
    validas = [(i + 1, org) for i, org in enumerate(orgs) if org.get("locations")]
    for num, org in validas:
        n = len(org["locations"])
        print(f"  [{num:2d}] {org['name']}  ({n} ubicación{'es' if n != 1 else ''})")

    print("\nIntroduce los números separados por comas (ej: 1,3) o 'all' para todas:")
    try:
        respuesta = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(0)

    if respuesta.lower() == "all":
        seleccionadas = [org for org in orgs if org.get("locations")]
    else:
        try:
            indices = {int(x.strip()) for x in respuesta.split(",") if x.strip()}
        except ValueError:
            print("Entrada no válida.")
            sys.exit(1)
        nums_validos = {num for num, _ in validas}
        invalidos = indices - nums_validos
        if invalidos:
            print(f"Números no válidos: {invalidos}")
            sys.exit(1)
        seleccionadas = [org for num, org in validas if num in indices]

    return seleccionadas


def _calcular_y_mostrar_coste(ubicaciones: list[dict], fecha_entrega: str,
                               force: bool, store: dict) -> tuple[list[dict], int]:
    """
    Muestra tabla de ubicaciones seleccionadas con estado actual y calcula el coste.
    Devuelve (ubicaciones_a_procesar, n_attrs).
    """
    print("\n" + "─" * 70)
    print(f"{'UBICACIÓN':<35} {'ORG':<20} {'ESTADO'}")
    print("─" * 70)

    a_procesar = []
    for loc in ubicaciones:
        uuid      = loc["uuid"]
        nombre    = loc.get("name", uuid)[:34]
        org_name  = loc.get("_org", "")[:19]
        ya_hoy    = _ya_enriquecida_hoy(uuid, store, fecha_entrega)
        tiene_geo = any(
            any(s.get(c) is not None for c in GEO_FEATURE_COLS)
            for s in store.get(uuid, [])
            if isinstance(s, dict)
        )

        if ya_hoy and not force:
            estado = "↩  ya enriquecida hoy (--force para reejecutar)"
        else:
            if ya_hoy:
                estado = "⚠  re-enriquecimiento forzado"
            elif tiene_geo:
                estado = "↑  actualización (tiene histórico)"
            else:
                estado = "★  primera entrega"
            a_procesar.append(loc)

        print(f"  {nombre:<35} {org_name:<20} {estado}")

    print("─" * 70)

    n_locs  = len(a_procesar)
    n_attrs = _UNIQUE_VARS * _RINGS * n_locs
    coste   = n_attrs * _USD_PER_1000 / 1000

    print(f"\n  Variables únicas en analysisVariables : {_UNIQUE_VARS}")
    print(f"  Ring buffers (400 / 800 / 1 200 m)    : {_RINGS} áreas por ubicación")
    print(f"  Ubicaciones a procesar                 : {n_locs}")
    print(f"  ──────────────────────────────────────────────────────────")
    print(f"  Atributos totales ({_UNIQUE_VARS} × {_RINGS} × {n_locs})      : {n_attrs:,}")
    print(f"  Coste estimado (1 USD/1 000 attrs)     : ${coste:.4f} USD  (~€{coste * 0.92:.4f})")
    print()

    return a_procesar, n_attrs


def main():
    parser = argparse.ArgumentParser(
        description="Enriquecimiento Esri con selección de ubicaciones y preview de coste"
    )
    parser.add_argument("--org",     nargs="+", metavar="NOMBRE",
                        help="Filtrar por nombre de organización (parcial, insensible a mayúsculas)")
    parser.add_argument("--all",     action="store_true",
                        help="Procesar todas las ubicaciones del fichero")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo previsualizar coste, no ejecutar ninguna llamada a Esri")
    parser.add_argument("--force",   action="store_true",
                        help="Re-enriquecer aunque ya exista un snapshot de la fecha indicada")
    parser.add_argument("--fecha",   default=None, metavar="YYYY-MM-DD",
                        help="Fecha de entrega (defecto: hoy)")
    args = parser.parse_args()

    fecha_entrega = args.fecha or date.today().isoformat()

    orgs  = _cargar_todas()
    store = _cargar_geo_store()

    # ── Selección de organizaciones ──────────────────────────────────────────
    if args.all:
        orgs_sel = [org for org in orgs if org.get("locations")]
    elif args.org:
        filtros  = [f.lower() for f in args.org]
        orgs_sel = [
            org for org in orgs
            if any(f in org.get("name", "").lower() for f in filtros)
            and org.get("locations")
        ]
        if not orgs_sel:
            print(f"No se encontró ninguna organización que coincida con: {args.org}")
            sys.exit(1)
    else:
        orgs_sel = _seleccionar_ubicaciones_interactivo(orgs)

    # Aplanar a lista de ubicaciones añadiendo el nombre de la org
    locs_sel = []
    for org in orgs_sel:
        for loc in org.get("locations", []):
            locs_sel.append({**loc, "_org": org.get("name", "")})

    if not locs_sel:
        print("No hay ubicaciones para procesar.")
        sys.exit(0)

    print(f"\n{'=' * 70}")
    print(f"  Esri GeoEnrichment — previsualización de coste")
    print(f"  Fecha de entrega: {fecha_entrega}")
    print(f"{'=' * 70}")

    a_procesar, n_attrs = _calcular_y_mostrar_coste(locs_sel, fecha_entrega, args.force, store)

    if not a_procesar:
        print("  Todas las ubicaciones seleccionadas ya tienen datos de hoy.")
        print("  Usa --force para reejecutar de todas formas.")
        sys.exit(0)

    if args.dry_run:
        print("  [dry-run] No se ejecutará ninguna llamada a Esri.")
        sys.exit(0)

    # ── Confirmación ─────────────────────────────────────────────────────────
    print(f"  ¿Ejecutar enriquecimiento? (s/N): ", end="", flush=True)
    try:
        confirmacion = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(0)

    if confirmacion not in ("s", "si", "sí", "y", "yes"):
        print("Cancelado.")
        sys.exit(0)

    # ── Ejecución ─────────────────────────────────────────────────────────────
    from src.data_ingestion.esri_client import fetch_enrich
    from src.data_ingestion.ingesta_geo import ingestar_snapshot_esri

    print(f"\n{'─' * 70}")
    ok = 0
    errores = []

    for loc in a_procesar:
        uuid   = loc["uuid"]
        nombre = loc.get("name", uuid)
        lat    = loc.get("lat")
        lon    = loc.get("lon")

        print(f"  → {nombre} ({uuid[:8]}…)", end=" ", flush=True)
        try:
            valores   = fetch_enrich(uuid, lat=lat, lon=lon)
            resultado = ingestar_snapshot_esri(uuid, valores, fecha_entrega)
            n_feat    = len(resultado["features_registradas"])
            n_snap    = resultado["snapshots_creados"]
            print(f"OK  {n_feat} features, {n_snap} snapshot(s)")
            ok += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            errores.append({"uuid": uuid, "nombre": nombre, "error": str(exc)})

    print(f"{'─' * 70}")
    print(f"\n  Completado: {ok}/{len(a_procesar)} ubicaciones OK")

    if errores:
        print(f"\n  Errores ({len(errores)}):")
        for e in errores:
            print(f"    • {e['nombre']}: {e['error']}")

    coste_real = (_UNIQUE_VARS * _RINGS * ok) * _USD_PER_1000 / 1000
    print(f"\n  Coste real estimado: ${coste_real:.4f} USD (~€{coste_real * 0.92:.4f})")
    print(f"  (Verifica en: https://location.arcgis.com → Usage)")


if __name__ == "__main__":
    main()
