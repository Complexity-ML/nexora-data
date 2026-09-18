import argparse
import json
import sys
from pathlib import Path

from .ingestion.catalog import scan
from .ingestion.connection import source_connection
from .ingestion.extract import extract
from .ingestion.selection import Selection
from .storage.minio import publish


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nexora-data — scanner SQL et Bronze Parquet")
    commands = parser.add_subparsers(dest="command", required=True)
    scanner = commands.add_parser(
        "scan", help="Catalogue des métadonnées, sans lire les lignes métier"
    )
    scanner.add_argument("--schema", action="append", help="Répéter pour limiter le périmètre")
    scanner.add_argument("--output", type=Path, required=True)
    extractor = commands.add_parser("extract", help="Extraire uniquement une sélection explicite")
    extractor.add_argument("--selection", type=Path, required=True)
    extractor.add_argument("--output", type=Path, help="Export local optionnel ; MinIO par défaut")
    args = parser.parse_args(argv)
    try:
        if args.command == "scan" and args.output.exists():
            raise FileExistsError("Le catalogue de sortie existe déjà.")
        selection = (
            Selection.model_validate_json(args.selection.read_text())
            if args.command == "extract"
            else None
        )
        with source_connection() as conn:
            if args.command == "scan":
                result = scan(conn, args.schema)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation prevents accidentally replacing a previous catalogue.
                with args.output.open("x", encoding="utf-8") as stream:
                    json.dump(result, stream, indent=2, ensure_ascii=False, default=str)
                print(f"Catalogue créé : {args.output} ({len(result['objects'])} objets)")
            else:
                location = (
                    extract(conn, selection, args.output)
                    if args.output is not None
                    else publish(conn, selection)["directory"]
                )
                print(f"Extraction publiée : {location}")
    except Exception as exc:  # noqa: BLE001 — sanitize all driver errors at the CLI boundary
        # Driver errors may embed credentials, DSNs, SQL and business values.
        print(
            f"Échec ({type(exc).__name__}). Vérifier connexion, permissions, sélection et types. "
            "Aucun détail sensible du pilote n’est affiché.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
