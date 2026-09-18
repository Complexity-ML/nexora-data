# nexora-data

Nexora-data est un outil Python d’exploration de bases SQL et d’extraction de données au format Parquet.

## Fonctionnalités

- Interface web Python/Dash pour explorer la source et lancer les extractions.
- Découverte des schémas, tables, vues et métadonnées des champs.
- Consultation des types, clés et relations déclarées.
- Sélection des tables et colonnes à extraire.
- Extraction par lots avec un manifeste de provenance.

## Installation

Python 3.11 ou supérieur.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Démonstration

```sh
nexora-demo
nexora-dash --demo
```

Interface locale : http://127.0.0.1:8051. Le générateur crée une base SQLite fictive de 90 jours ; il refuse d’écraser une base existante.

## Utilisation

Configurer la connexion SQL dans la variable d’environnement `NEXORA_SOURCE_URL`, puis lancer :

```sh
nexora-data scan --output data/catalog.json
nexora-data extract --selection examples/selection.json --output data/bronze
```

Les sources Python se trouvent dans `nexora/src/`.

Voir le [guide du scanner et de l’extracteur](docs/scanner-extractor.md).
