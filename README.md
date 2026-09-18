# nexora-data

Nexora-data est un outil Python/Dash d’exploration de bases SQL et d’extraction de données Parquet vers MinIO.

## Fonctionnalités

- Scan des schémas, tables, vues et métadonnées des champs.
- Consultation des types, clés et relations déclarées.
- Collecte automatique de tous les objets et champs accessibles, avec limite de lignes facultative.
- Extraction par lots vers MinIO avec un manifeste de provenance.
- Jeu de données SQL fictif pour la démonstration.

## Démarrage avec Docker

```sh
python3 scripts/configure_local.py
docker compose up -d --build
```

- Application : http://127.0.0.1:8051
- Console MinIO : http://127.0.0.1:9001

Les identifiants locaux sont générés dans `.env`, exclu de Git. Le script refuse d’écraser ce fichier.

Les Parquet et leurs manifestes sont stockés dans le bucket `nexora-data`, sous `bronze/<source>/<extraction>/`. Les volumes Docker conservent les données entre les redémarrages.

## Développement Python

Python 3.11 ou supérieur.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Les sources se trouvent dans `nexora/src/`.

Voir le [guide d’utilisation](docs/scanner-extractor.md).
