# Scanner SQL et extraction MinIO

## Stack Docker locale

```sh
python3 scripts/configure_local.py
docker compose up -d --build
docker compose ps
```

Trois services : `minio`, `minio-init` (création du bucket et du compte applicatif) et `app` (Dash/Gunicorn). Un seul worker applicatif conserve la file locale des traitements ; quatre threads répondent aux requêtes HTTP. Le service applicatif attend la réussite de l’initialisation MinIO.

Les ports sont exposés uniquement sur `127.0.0.1` : 8051 pour Dash, 9000 pour S3, 9001 pour la console MinIO. Le compte applicatif MinIO accède au bucket configuré et aux objets sous `bronze/`. Les identifiants administrateur restent réservés à MinIO et au service d’initialisation.

Les volumes `minio-data` et `demo-data` stockent respectivement les objets S3 et la base SQL fictive. `docker compose down` arrête les services sans supprimer ces volumes. `docker compose down -v` efface leurs données.

## Parcours Dash

1. Facultativement, lancer le scan pour consulter le catalogue complet.
2. Renseigner une limite de lignes par table pour les essais, ou laisser le champ vide.
3. Lancer la collecte : tous les objets et leurs colonnes sont inclus automatiquement.
4. Consulter le résultat conservé dans MinIO.

Le scan consulte les métadonnées, sans échantillonnage des lignes métier ni comptage complet. Il remonte types, nullabilité, valeurs par défaut, clés, index et commentaires disponibles. Les métadonnées non prises en charge sont signalées. Les relations non déclarées ne sont pas devinées. Les vues matérialisées ne sont pas encore listées séparément.

La connexion reste côté serveur. Les opérations sont exécutées une à la fois en arrière-plan. Les états des traitements sont en mémoire et disparaissent au redémarrage. Cette interface locale ne fournit pas d’authentification ni d’isolation multi-utilisateur.

## Source SQL réelle

Dans `.env`, définir `NEXORA_DEMO=0` et `NEXORA_SOURCE_URL` avec une URL SQLAlchemy, puis recréer le service `app`.

Utiliser un compte SQL en lecture seule. PostgreSQL active également une transaction READ ONLY et un délai de 60 secondes par instruction. SQLite active `query_only`. SQL Server dépend des permissions du compte source.

- SQLite : inclus et testé dans la démonstration.
- PostgreSQL : pilote psycopg inclus dans l’image Docker.
- SQL Server : dialecte préparé ; nécessite `pip install -e '.[mssql]'` et un pilote ODBC système adapté. Ce pilote n’est pas inclus dans l’image fournie.

Les connexions PostgreSQL et SQL Server doivent être validées sur la base cible. Ne pas committer les URL privées ou identifiants.

## Commandes Python

Dans un environnement virtuel :

```sh
pip install -e .
nexora-demo
export NEXORA_SOURCE_URL="sqlite:///data/enterprise.sqlite"
nexora-data scan --schema main --output data/catalog.json
nexora-data extract --selection examples/selection.json
nexora-dash --demo
```

Pour les exports MinIO hors Docker, définir dans l’environnement : `NEXORA_S3_ENDPOINT` (par exemple `http://127.0.0.1:9000`), `NEXORA_S3_BUCKET`, `NEXORA_S3_ACCESS_KEY` et `NEXORA_S3_SECRET_KEY`. Les commandes Python ne chargent pas `.env` automatiquement. MinIO doit être démarré et le bucket initialisé. L’option `--output` de `extract` permet explicitement un export local pour les tests ; l’interface utilise MinIO.

`examples/selection.json` définit un label de provenance, une taille de lot et des objets avec schéma, nom, colonnes et limite. La limite vaut 10 000 lignes par défaut ; `null` demande une extraction complète en CLI. Dans Dash, une limite positive est facultative ; un champ vide demande la collecte complète.

Une extraction limitée n’est ni ordonnée ni un échantillon statistique. Le manifeste signale la troncature. Les identifiants SQL sont cités par SQLAlchemy ; aucune requête SQL libre n’est acceptée.

## Objets Parquet

```text
s3://nexora-data/bronze/<source-label>/<run-id>/
  object-0000.parquet
  manifest.json
```

Les Parquet sont préparés dans un répertoire temporaire, envoyé vers MinIO puis supprimé. Aucun Parquet permanent n’est écrit dans le volume de la base de démonstration. Le disque temporaire doit pouvoir contenir l’extraction ; la mémoire est traitée par lots, sous réserve du buffering du pilote SQL.

Le manifeste est envoyé en dernier et marque la publication du résultat. Il contient les champs sélectionnés, la source logique, les horaires UTC, la quantité de lignes, la troncature, le schéma Arrow, les clés S3, les tailles et empreintes SHA-256. Il ne contient pas les identifiants de connexion. Les lecteurs ne doivent utiliser que les extractions possédant un manifeste.

Les tailles et métadonnées d’empreinte sont vérifiées après envoi. Les tests relisent aussi le Parquet et recalculent son empreinte. En cas d’erreur, un nettoyage des objets est tenté ; une panne réseau ou un arrêt brutal peut laisser des objets sans manifeste. Aucun mécanisme de purge automatique n’est encore fourni.

La publication ne garantit pas un snapshot transactionnel cohérent de plusieurs tables SQL : le manifeste l’indique. Chaque lancement crée un snapshot indépendant ; il n’y a pas encore de collecte incrémentale ni de reprise d’une extraction interrompue.

Les types simples, dates/heures, UUID et décimaux à précision déclarée sont pris en charge. Un type inconnu provoque une erreur plutôt qu’une conversion silencieuse. Les valeurs nulles et tables vides conservent leur schéma. Les données sont conservées telles qu’extraites : sélectionner uniquement les champs autorisés.

## Données fictives et tests

Le générateur produit par défaut 4 entités, 6 logiciels, 240 utilisateurs, 240 machines, 720 installations et 90 jours d’observations, du 20 juin au 17 septembre 2026. Les noms et identifiants sont inventés. La graine fixe permet de reproduire les données ; un fichier existant n’est jamais écrasé.

Sept tables : `organizations`, `software`, `users`, `machines`, `installations`, `collection_coverage`, `usage_observations`. Deux vues : `installation_inventory`, `observed_usage`. Les jours de collecte manquants sont distingués des jours observés sans activité.

```sh
pip install pytest ruff 'moto[s3]'
pytest -q
ruff check .
```

Pour vérifier la stack en cours d’exécution, sans navigateur :

```sh
docker compose exec -T app python < scripts/smoke_stack.py
```

Ce test appelle les endpoints Dash, scanne la base fictive, extrait 100 observations dans MinIO, relit le Parquet et vérifie son empreinte. Il crée une extraction de test dans le bucket et nécessite le mode démonstration.
