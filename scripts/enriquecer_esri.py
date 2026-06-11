#!/usr/bin/env python3
"""
CLI para enriquecer ubicaciones con datos Esri GeoEnrichment.

Uso:
  python scripts/enriquecer_esri.py --org "Miniso"
  python scripts/enriquecer_esri.py --uuid 67034276-0d01-4c90-a363-fa75699a19a4 db01e2ed-...
  python scripts/enriquecer_esri.py --all
  python scripts/enriquecer_esri.py --org "Miniso" --dry-run
  python scripts/enriquecer_esri.py --estado

Opciones:
  --org <nombre>      Procesa todas las ubicaciones activas de la org (substring, sin caso)
  --uuid <uuid...>    Uno o más UUIDs de ubicación concretos
  --all               Todas las ubicaciones activas (cuidado con el coste)
  --fecha <ISO>       Fecha de entrega (por defecto: hoy)
  --dry-run           Muestra qué haría sin escribir nada
  --estado            Muestra estado actual de geo snapshots por ubicación y sale
"""
import argparse
import sys
import os

# Asegurar que el raíz del proyecto está en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


def cmd_estado():
    from src.data_ingestion.prefetch.geo import listar_estado
    filas = listar_estado(verbose=False)
    if not filas:
        print("No hay snapshots geo registrados.")
        return
    print(f"{'Ubicación':<40} {'Features':>8} {'Última entrega'}")
    print("-" * 65)
    for f in filas:
        from src.db.store import get_conn
        nombre = get_conn().execute(
            "SELECT nombre FROM dim_ubicaciones WHERE location_uuid = ?",
            [f["location_uuid"]],
        ).fetchone()
        label = nombre[0] if nombre else f["location_uuid"]
        print(f"{label:<40} {f['features_con_dato']:>3}/{f['features_total']:<4}  {f['ultima_entrega']}")


def cmd_enriquecer(uuids: list, org: str, fecha: str, dry_run: bool):
    from src.db.store import get_conn
    from src.data_ingestion.esri_client import fetch_enrich
    from src.data_ingestion.prefetch.geo import ingestar_snapshot_esri

    conn = get_conn()

    if uuids:
        rows = conn.execute(
            f"SELECT location_uuid, nombre, lat, lon FROM dim_ubicaciones "
            f"WHERE location_uuid IN ({','.join('?' * len(uuids))}) AND activa = TRUE",
            uuids,
        ).fetchall()
        no_encontrados = set(uuids) - {r[0] for r in rows}
        if no_encontrados:
            print(f"[warn] UUIDs no encontrados o inactivos: {no_encontrados}", file=sys.stderr)
    elif org:
        rows = conn.execute(
            "SELECT l.location_uuid, l.nombre, l.lat, l.lon "
            "FROM dim_ubicaciones l "
            "JOIN dim_organizaciones o ON o.org_uuid = l.org_uuid "
            "WHERE LOWER(o.nombre) LIKE ? AND l.activa = TRUE",
            [f"%{org.lower()}%"],
        ).fetchall()
        if not rows:
            print(f"[error] Ninguna ubicación activa para org '{org}'", file=sys.stderr)
            sys.exit(1)
    else:
        rows = conn.execute(
            "SELECT location_uuid, nombre, lat, lon FROM dim_ubicaciones WHERE activa = TRUE"
        ).fetchall()

    print(f"{'[dry-run] ' if dry_run else ''}Procesando {len(rows)} ubicación(es)...\n")

    ok = 0
    errores = 0
    for location_uuid, nombre, lat, lon in rows:
        try:
            valores = fetch_enrich(location_uuid, lat=lat, lon=lon)
            if dry_run:
                n_reales = sum(1 for v in valores.values() if v is not None and not str(v).startswith("_"))
                print(f"  [dry-run] {nombre} ({location_uuid})")
                print(f"           {n_reales} features con valor")
                for k, v in valores.items():
                    if k.startswith("_"):
                        continue
                    print(f"           {k}: {v}")
                print()
                ok += 1
            else:
                resultado = ingestar_snapshot_esri(location_uuid, valores, fecha)
                n_feat = len(resultado["features_registradas"])
                tipo = "primera entrega" if resultado["primera_entrega"] else "actualización"
                print(f"  [ok] {nombre} — {tipo}, {n_feat} features")
                ok += 1
        except Exception as e:
            print(f"  [error] {nombre} ({location_uuid}): {e}", file=sys.stderr)
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
    group.add_argument("--org",    metavar="NOMBRE", help="Filtrar por nombre de organización")
    group.add_argument("--uuid",   metavar="UUID", nargs="+", help="UUIDs de ubicación concretos")
    group.add_argument("--all",    action="store_true", help="Todas las ubicaciones activas")
    group.add_argument("--estado", action="store_true", help="Ver estado actual de snapshots geo")

    parser.add_argument("--fecha",   metavar="YYYY-MM-DD", default=None, help="Fecha de entrega (por defecto: hoy)")
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada, solo muestra qué haría")

    args = parser.parse_args()

    if args.estado:
        cmd_estado()
        return

    cmd_enriquecer(
        uuids=args.uuid or [],
        org=args.org or ("" if args.all else ""),
        fecha=args.fecha,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
