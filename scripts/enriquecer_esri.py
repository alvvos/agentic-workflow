#!/usr/bin/env python3
"""
CLI para enriquecer ubicaciones con datos Esri GeoEnrichment.

Uso:
  python scripts/enriquecer_esri.py --org "Miniso"
  python scripts/enriquecer_esri.py --uuid 67034276-0d01-4c90-a363-fa75699a19a4
  python scripts/enriquecer_esri.py --all
  python scripts/enriquecer_esri.py --org "Miniso" --dry-run
  python scripts/enriquecer_esri.py --estado

Opciones:
  --org <nombre>      Procesa todas las ubicaciones activas de la org (substring, sin caso)
  --uuid <uuid...>    Uno o más UUIDs de ubicación concretos
  --all               Todas las ubicaciones activas (cuidado con el coste de API)
  --fecha <ISO>       Fecha de entrega (por defecto: hoy)
  --dry-run           Muestra qué haría sin escribir nada
  --estado            Muestra estado actual de geo snapshots por ubicación y sale
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()


def cmd_estado():
    from src.data_ingestion.geo import listar_estado

    filas = listar_estado(verbose=False)
    if not filas:
        print("No hay ubicaciones activas.")
        return
    print(f"{'Ubicación':<40} {'Snapshots':>10} {'Datos'}")
    print("-" * 60)
    for f in filas:
        mark = "✓" if f["tiene_datos"] else "✗"
        print(f"  {f['nombre']:<38} {f['n_snapshots']:>5}      {mark}")


def cmd_enriquecer(uuids: list, org: str, fecha: str | None, dry_run: bool):
    from src.data_ingestion.esri_client import fetch_geoenrich
    from src.data_ingestion.geo import calcular_scores_poi, ingestar_snapshot_esri
    from src.db.store import get_conn

    conn = get_conn()

    if uuids:
        placeholders = ",".join("?" * len(uuids))
        rows = conn.execute(
            f"SELECT ubicacion_id, nombre, lat, lon FROM ubicaciones "
            f"WHERE ubicacion_id IN ({placeholders}) AND activa = TRUE",
            uuids,
        ).fetchall()
        no_encontrados = set(uuids) - {r[0] for r in rows}
        if no_encontrados:
            print(f"[warn] UUIDs no encontrados o inactivos: {no_encontrados}", file=sys.stderr)
    elif org:
        rows = conn.execute(
            "SELECT u.ubicacion_id, u.nombre, u.lat, u.lon "
            "FROM ubicaciones u "
            "JOIN organizaciones o ON o.org_id = u.org_id "
            "WHERE LOWER(o.nombre) LIKE ? AND u.activa = TRUE",
            [f"%{org.lower()}%"],
        ).fetchall()
        if not rows:
            print(f"[error] Ninguna ubicación activa para org '{org}'", file=sys.stderr)
            sys.exit(1)
    else:
        rows = conn.execute(
            "SELECT ubicacion_id, nombre, lat, lon FROM ubicaciones "
            "WHERE activa = TRUE AND lat IS NOT NULL AND lon IS NOT NULL"
        ).fetchall()

    if not rows:
        print("[warn] Ninguna ubicación encontrada.")
        return

    print(f"{'[dry-run] ' if dry_run else ''}Procesando {len(rows)} ubicación(es)...\n")

    ok = 0
    errores = 0
    for ubicacion_id, nombre, lat, lon in rows:
        if lat is None or lon is None:
            print(f"  [skip] {nombre} — sin coordenadas", file=sys.stderr)
            errores += 1
            continue
        try:
            valores = fetch_geoenrich(ubicacion_id, lat=lat, lon=lon)
            valores.update(calcular_scores_poi(ubicacion_id))
            n_valores = sum(1 for v in valores.values() if v is not None)
            if dry_run:
                print(f"  [dry-run] {nombre} ({ubicacion_id[:8]}…)")
                print(f"           {n_valores} features con valor")
                for k, v in sorted(valores.items()):
                    if v is not None:
                        print(f"           {k}: {v}")
                print()
                ok += 1
            else:
                resultado = ingestar_snapshot_esri(ubicacion_id, valores, fecha)
                tipo = "primera entrega" if resultado["primera_entrega"] else "actualización"
                print(f"  [ok] {nombre} — {tipo}, {resultado['n_features']} features")
                ok += 1
        except Exception as e:
            print(f"  [error] {nombre} ({ubicacion_id}): {e}", file=sys.stderr)
            errores += 1

    print(f"\n{'─' * 40}")
    print(f"Completado: {ok} ok, {errores} errores")


def main():
    parser = argparse.ArgumentParser(
        description="Enriquece ubicaciones con datos Esri GeoEnrichment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--org", metavar="NOMBRE", help="Filtrar por nombre de organización")
    group.add_argument("--uuid", metavar="UUID", nargs="+", help="UUIDs de ubicación concretos")
    group.add_argument("--all", action="store_true", help="Todas las ubicaciones activas")
    group.add_argument("--estado", action="store_true", help="Ver estado actual de snapshots geo")

    parser.add_argument(
        "--fecha", metavar="YYYY-MM-DD", default=None, help="Fecha de entrega (por defecto: hoy)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="No escribe nada, solo muestra qué haría"
    )

    args = parser.parse_args()

    if args.estado:
        cmd_estado()
        return

    cmd_enriquecer(
        uuids=args.uuid or [],
        org=args.org or "",
        fecha=args.fecha,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
