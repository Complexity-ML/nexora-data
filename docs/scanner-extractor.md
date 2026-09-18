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

## Analyse et projection

En mode démonstration, le DW fictif est la seule source. Le démarrage ne génère aucune donnée et ne lance aucune collecte. Les résultats déjà publiés sont restaurés depuis MinIO après un rafraîchissement. Le DW est préparé explicitement ; le scan et la collecte se lancent depuis Sources. Chaque nouvelle collecte complète et valide devient la source de l’analyse ; les essais tronqués ne la remplacent pas. Le dashboard affiche les résultats de la collecte publiée, sans redémarrage. Extractions distingue la collecte utilisée de son historique. Les vues sont exportées mais ne sont pas recomptées dans les indicateurs, calculés à partir des tables d’observations.

L’accueil calcule le nombre d’utilisateurs actifs distincts par jour et logiciel, avec filtres par entité et période inclusive. Une journée sans couverture complète du périmètre est absente de la courbe, et non remplacée par zéro. Le nombre d’installations est mesuré à la fin de la période choisie.

La projection produit sept valeurs quotidiennes après cette date. Elle ajuste une tendance linéaire pour chaque jour de semaine sur au plus 56 jours historiques, avec au moins quatre observations de chaque jour de semaine et une dernière journée complète. Les valeurs sont bornées entre zéro et la population disposant du logiciel à la date d’origine. Cette hypothèse de population constante ne représente pas une capacité contractuelle. Une période trop courte ou incomplète affiche « Données insuffisantes ».

L’erreur moyenne absolue à J+7 est évaluée sur au plus 14 dates historiques : chaque estimation utilise uniquement les données connues sept jours avant sa cible, y compris la population installée à cette date. La référence affiche l’erreur obtenue en reprenant l’usage de la semaine précédente. Aucune supériorité sur cette référence n’est supposée et aucun intervalle de confiance non calibré n’est affiché.

Cette version calcule les indicateurs avec Python à partir d’un snapshot Parquet cohérent. Elle ne fournit pas encore de pipeline Silver/Gold PySpark. Pour une source réelle, un adaptateur analytique devra définir les correspondances entre les champs et les observations d’usage ; le scanner seul ne peut pas les déduire.

Vérification de l’accueil, des filtres et de la navigation par HTTP :

```sh
docker compose exec -T app python < scripts/smoke_analytics.py
```

Dans **Extractions**, le bouton **Supprimer** retire les Parquet et le manifeste de la collecte sélectionnée après confirmation. La source SQL et les autres extractions sont conservées. Les graphiques liés à une collecte supprimée sont retirés ; une nouvelle collecte peut être lancée depuis Sources.

### Comparaison tendance et arbre

Les deux méthodes utilisent les observations complètes des 56 derniers jours. La tendance ajuste une droite par jour de semaine ; l’arbre de régression utilise la date et le jour de semaine, avec une profondeur maximale de 3 et au moins 4 observations par feuille. Ces paramètres sont fixes, sans recherche d’hyperparamètres.

La MAE à J+7 est mesurée sur les mêmes dates historiques disponibles (14 au maximum). Pour chaque date testée, les deux méthodes utilisent uniquement l’historique disponible sept jours auparavant. Une erreur plus faible indique une meilleure performance sur cette période, sans garantir les prévisions futures. Aucune pondération de classes : la cible est un nombre d’utilisateurs.

### Opportunités de revue SAM

Le menu Opportunités exploite la collecte analytique publiée. Il signale les installations sans usage ou actives seulement 1 à 2 jours sur les 28 derniers jours. Il exige une installation antérieure à la période et une couverture complète de l’entité. Les installations avec une couverture insuffisante sont comptées séparément, jamais présentées comme inactives.

Un signal de baisse compare les utilisateurs actifs quotidiens moyens sur deux périodes consécutives de 28 jours, avec une couverture complète et les mêmes installations présentes avant les deux périodes. Le seuil de détection est une baisse d’au moins 30 %. Ces seuils sont des critères de revue explicites, pas des règles contractuelles. Les signaux peuvent concerner un même périmètre et ne doivent pas être additionnés en licences récupérables.

Chaque ligne indique le logiciel, l’entité, les observations et la couverture. Le lien Voir l’analyse ouvre Plotly avec le même logiciel, la même entité et la période concernée. La décision et la qualification des économies restent au SAM.

### Actualisation par comparaison SQL

Une collecte complète depuis Sources compare les blocs côté SQL. La première collecte initialise les Parquet partitionnés. Les suivantes récupèrent uniquement les lignes des blocs différents, réutilisent les blocs inchangés et retirent du nouveau manifeste les blocs supprimés. Une modification d’une seule ligne peut nécessiter de récupérer son bloc entier. Les collectes limitées restent des essais indépendants.

Une clé primaire entière utilise des plages de 10 000 identifiants. Les autres tables et vues utilisent 256 groupes déterministes. Les empreintes ordonnées incluent le contenu, les valeurs nulles et la multiplicité des lignes. Une modification de structure invalide la comparaison de l’objet. Le DW doit toujours parcourir les données pour calculer ces empreintes. Le gain porte sur le transfert et l’écriture des Parquet, pas sur la suppression du travail SQL.

Les fichiers sont immuables et les manifestes désignent une version complète. La publication intervient après les fichiers. Les lectures analytiques restent attachées à leur manifeste et les suppressions conservent les fragments référencés par une autre extraction. La coordination locale suppose un seul processus applicatif, comme la configuration Gunicorn fournie. Ne pas exécuter plusieurs collecteurs indépendants sur la même source.

SQLite est vérifié avec la démonstration. Les requêtes PostgreSQL et SQL Server restent à valider sur le moteur réel du DW et ses types. PostgreSQL utilise REPEATABLE READ. SQL Server nécessite l’isolation SNAPSHOT activée par l’administrateur. Aucune migration ni activation de paramètre du DW n’est effectuée par l’application. Aucun transfert réduit n’est garanti pour un moteur non validé. Le chargement analytique en mémoire reste celui du prototype et n’a pas été validé sur 92 millions de lignes.

Opportunités présente désormais une ligne par logiciel, puis les signaux par entité et enfin les installations. Chaque niveau affiche au plus 25 lignes. Cette présentation progressive ne modifie pas la collecte du DW.
