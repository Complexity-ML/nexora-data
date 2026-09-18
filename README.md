# nexora-data

Nexora-data est une application Python/Dash d’analyse de l’usage logiciel, avec collecte SQL et stockage Parquet dans MinIO.

## Fonctionnalités

- Dashboard d’usage avec filtres par logiciel, entité et période.
- Historique, couverture des observations et comparaison tendance / arbre de régression à J+7.
- Historique et suppression individuelle des extractions dans MinIO, sans modifier la source SQL.

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

Aucune démo ni collecte ne se lance au démarrage. Pour présenter le parcours avec un DW fictif, charger explicitement la base puis activer `NEXORA_DEMO=1` dans `.env` :

```sh
docker compose run --rm app nexora-demo --output /app/data/enterprise.sqlite
docker compose up -d app
```

Dans **Sources**, lancer le scan puis la collecte. Les résultats de cette collecte apparaissent ensuite dans **Analyse**. Les anciennes extractions restent accessibles dans **Extractions**.

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
