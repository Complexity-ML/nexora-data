# Scanner SQL et extracteur Bronze

## Installation

Depuis `/Users/boris/Dev/nexora-data` :

```sh
pip install -e .
nexora-data --help
```

Python 3.11 ou supérieur.

## Démonstration locale reproductible

Les données de cette démonstration sont fictives. Le script refuse d’écraser une base existante.

```sh
python examples/create_demo.py
export NEXORA_SOURCE_URL="sqlite:///data/demo.sqlite"
nexora-data scan --schema main --output data/catalog.json
nexora-data extract --selection examples/selection.json --output data/bronze
```

Le catalogue JSON donne les schémas, tables et vues, champs/types, nullabilité, valeurs par défaut, colonnes calculées/identités si exposées, clés primaires, clés étrangères, index et commentaires disponibles. Une métadonnée non prise en charge par le pilote est indiquée explicitement. Les noms et commentaires peuvent contenir des informations internes : conserver les catalogues dans un stockage autorisé.

Le scan n’échantillonne aucune ligne métier et ne lance pas de COUNT sur les tables. La découverte ne déduit pas de relations non déclarées et n’interprète pas automatiquement la sémantique des champs. Une erreur de permission ou de réflexion interrompt le scan ; aucun catalogue prétendument complet n’est alors publié. Les vues matérialisées ne sont pas encore listées séparément.

Sans `--schema`, les schémas retournés par le pilote sont explorés, hors schémas système connus. Sur une grande base, utiliser plusieurs `--schema` pour limiter le périmètre. La visibilité dépend des droits du compte source.

## Connexion à une base réelle

`NEXORA_SOURCE_URL` est lu dans l’environnement uniquement. Ne pas enregistrer sa valeur dans les fichiers du projet ou les commandes partagées. Aucun `.env` n’est chargé automatiquement.

- PostgreSQL : installer `pip install -e ".[postgres]"`, puis utiliser une URL SQLAlchemy `postgresql+psycopg`.
- SQL Server : installer `pip install -e ".[mssql]"`, ainsi que le pilote ODBC système adapté, puis utiliser une URL SQLAlchemy `mssql+pyodbc`.
- SQLite : inclus pour les tests et démonstrations.

Seul SQLite a été testé localement pour cette première version. Les adaptateurs PostgreSQL et SQL Server reposent sur les dialectes SQLAlchemy mais doivent être validés sur le moteur et le pilote réels. Les autres moteurs seront ajoutés après identification du DW.

Utiliser un compte source dédié avec droits de lecture uniquement. L’application n’émet aucune écriture métier. SQLite active `query_only`; PostgreSQL active une transaction READ ONLY et un délai maximal de 60 secondes par instruction. SQL Server dépend des autorisations du compte pour imposer la lecture seule : le programme ne prétend pas réduire ses privilèges. Les délais réseau et requête SQL Server sont à régler avec le pilote choisi.

## Sélection explicite

Adapter `examples/selection.json` d’après le catalogue. Le nom de schéma est obligatoire, même pour le schéma par défaut. Chaque objet exige une liste explicite de colonnes.

- `source_label` : identifiant logique de provenance, sans mot de passe ni URL privée.
- `batch_size` : nombre maximum de lignes traitées par lot, entre 1 et 100 000. La mémoire dépend aussi de la taille de chaque ligne et du buffering du pilote.
- `row_limit` : 10 000 par défaut, ou `null` pour demander explicitement une extraction complète. Une ligne supplémentaire est lue au maximum pour détecter une troncature.

Les noms sont utilisés comme identifiants SQLAlchemy, jamais interpolés comme SQL libre. Toutes les sélections et les types Parquet sont validés avant la lecture des lignes métier. Pas de requête SQL arbitraire, de jointure automatique ou de filtre libre dans cette version. Créer une vue de lecture côté DW si un sous-ensemble complexe est nécessaire.

Une extraction limitée n’est pas un échantillon statistique ni un extrait ordonné : aucun ordre n’est garanti. Le manifeste indique si des lignes supplémentaires ont été exclues. Ne pas utiliser une extraction tronquée comme historique exhaustif d’usage.

## Sortie et intégrité

Chaque lancement produit un nouveau répertoire UUID :

```text
bronze/<run-id>/
  object-0000.parquet
  object-0001.parquet
  manifest.json
```

Le manifeste conserve le label source, le moteur, le schéma/table, les colonnes, les limites, les horaires UTC d’extraction, les nombres de lignes, la troncature, le schéma Arrow, les tailles et empreintes SHA-256. L’URL source et ses identifiants ne sont pas enregistrés. Les noms de fichiers sont indépendants des noms SQL.

Les dates métier ne sont ni inventées ni remplacées par la date d’extraction : sélectionner leurs colonnes explicitement. Les entiers, flottants, booléens, textes, binaires, dates/heures, UUID et décimaux à précision déclarée sont pris en charge. Un type inconnu ou complexe fait échouer l’extraction : aucune conversion silencieuse en texte. Pour un décimal sans précision déclarée, exposer un CAST approprié dans une vue. Les valeurs nulles et tables vides conservent leur schéma.

Le répertoire est préparé sous un nom `.partial`, puis renommé après réussite de tous les objets. Une erreur gérée supprime la préparation ; un arrêt brutal de la machine peut laisser un dossier `.partial` à ignorer/nettoyer. Les lecteurs doivent consulter uniquement les répertoires publiés avec manifeste. Cette atomicité concerne la sortie, pas une photographie transactionnelle cohérente de plusieurs tables source : le manifeste indique `cross_object_snapshot_guaranteed: false`.

Chaque extraction est un snapshot indépendant. Pas encore d’incrémental, de reprise d’un lot interrompu, de déduplication entre snapshots, de publication Gold ou de synchronisation des suppressions. Le Parquet est une couche Bronze brute ; sélectionner uniquement les champs autorisés. La pseudonymisation est à définir avant extraction de données personnelles réelles.

Les erreurs CLI affichent leur classe, sans traceback ni message brut du pilote susceptible de contenir des secrets ou des données. Un code retour non nul signale l’échec.

## Tests

```sh
pytest -q
ruff check .
```

Références techniques : [réflexion SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/reflection.html), [écriture Parquet avec PyArrow](https://arrow.apache.org/docs/python/parquet.html).
