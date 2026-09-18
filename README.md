# nexora-data

Projet d’analyse et de projection de l’usage logiciel.

## Cadrage — 18 septembre 2026

D’après la décision communiquée par le porteur du projet, les données seront centralisées dans Flexera. Nexora-data interrogera le **Data Warehouse alimenté par Flexera**. Le moteur du DW, ses vues, son schéma et le mode d’accès restent à confirmer.

Ce projet est indépendant du projet de commerce B2B et du dépôt Nexora-Dash existant.

## Chaîne cible

```text
Flexera → DW → extraction en lecture seule → Bronze Parquet
        → transformations PySpark Silver → Gold validé
        → analyse statistique et projection J+7 → Dash / Plotly
```

Le DW constitue le point d’entrée prévu. Aucun accès direct à Flexera ou via DIGIMON n’est requis dans ce cadrage. Le scanner et l’extracteur SQL sont implémentés ; la connexion au DW réel reste à configurer et valider.

## Périmètre analytique

- Installations et usage observés, selon les champs effectivement disponibles.
- Utilisateurs actifs, fréquence, évolution et pics uniquement si les observations permettent de les mesurer.
- Historisation des extractions avec date d’observation, date d’extraction et provenance.
- Projection à J+7 confrontée à une référence simple et évaluée chronologiquement.
- Statut explicite « Données insuffisantes » lorsque la couverture ne permet pas une analyse fiable.

Une absence d’observation ne constitue pas une preuve d’inactivité. Un nombre d’utilisateurs actifs quotidiens ne mesure pas la concurrence instantanée.

Le projet ne déduit ni droits acquis, ni licences disponibles, ni conformité, ni économies contractuelles à partir du seul usage. Le SAM conserve l’interprétation contractuelle.

Le POC initial utilisera des méthodes statistiques sans entraînement ML. Un arbre de régression pourra être évalué ultérieurement, avec entraînement explicite et validation temporelle. Un indicateur baisse/stable/hausse peut être dérivé de seuils documentés sans classifier.

## Organisation initiale

```text
src/nexora_data/
  ingestion/       # Connexion SQL, catalogue des métadonnées, extraction Parquet
  transformations/# Bronze → Silver → Gold
  analytics/      # Indicateurs d’usage et qualité
  forecasting/    # Projection J+7 et évaluation temporelle
  services/       # Accès aux résultats, indépendant de l’interface
 docs/
  source-contract.md
```

## Scanner et extracteur disponibles

- `nexora-data scan` : découvrir les métadonnées des tables et vues accessibles, sans lire les lignes métier.
- `nexora-data extract` : extraire des objets et champs explicitement sélectionnés, par lots, en Bronze Parquet avec manifeste de provenance.
- Connexion via `NEXORA_SOURCE_URL`, sans identifiants dans les sorties.
- Démonstration et tests SQLite ; connecteurs PostgreSQL / SQL Server préparés, à valider sur le DW réel.

Voir [le guide d’installation, de démonstration et de connexion](docs/scanner-extractor.md) et [la sélection exemple](examples/selection.json).

Le contrat source sera complété à partir du catalogue découvert ; il n’est pas nécessaire de cartographier manuellement toute la base avant le scan. L’exploration technique ne remplace pas la validation du sens des champs retenus pour l’analyse.

Les modules Silver, Gold, analytique et forecasting restent à implémenter. L’interface sera traitée après le backend. Les services Python du scanner et de l’extracteur peuvent ensuite être exposés par une API REST ; cette première version fournit une CLI.
