# nexora-data

Nexora-data est une application Python/Dash d’analyse de l’usage logiciel, avec collecte SQL et stockage Parquet dans MinIO.

## Fonctionnalités

- Dashboard d’usage avec filtres par logiciel, entité et période.
- Historique, couverture des observations et projection statistique J+7.
- Historique des extractions persistées dans MinIO.

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

L’accueil affiche automatiquement les résultats du jeu de données fictif. Le scanner est accessible dans **Sources**, et les collectes publiées dans **Extractions**.

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
