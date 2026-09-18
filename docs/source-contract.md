# Contrat source DW — à confirmer

Source prévue : Data Warehouse alimenté par Flexera.
Accès souhaité : lecture seule via vues ou tables explicitement autorisées.
Ne pas déposer de mots de passe, données personnelles ou coordonnées de connexion privées dans ce fichier.

| Élément | Information attendue |
|---|---|
| Moteur | SQL Server, PostgreSQL, Oracle, Snowflake ou autre : à confirmer |
| Accès | Connexion SQL/JDBC/ODBC ou exports fournis ; environnement réseau à confirmer |
| Objets disponibles | Schémas, vues et dictionnaire de données anonymisés |
| Granularité | Événement, session, installation, utilisateur/jour ou agrégat |
| Identifiants | Logiciel, version, machine, utilisateur pseudonymisé, organisation |
| Temporalité | Date d’observation, mise à jour, fuseau horaire et fréquence de rafraîchissement |
| Historique | Profondeur disponible, snapshots ou état courant seulement |
| Incrémental | Clé stable, watermark, corrections tardives et suppressions |
| Mesures | Définition exacte de l’usage et unités ; distinction utilisateur/machine/session |
| Couverture | Périmètres observés, retards, jours manquants et exclusions |
| Volume | Nombre de lignes, croissance quotidienne et limites de requête |

## Règles de conception retenues

1. Conserver les extractions Bronze avec provenance et identifiant d’exécution.
2. Préserver les identifiants stables et dédupliquer selon la granularité source vérifiée.
3. Distinguer date d’événement et date d’ingestion.
4. Valider les contrôles de qualité avant publication Gold.
5. Lire les tables d’une même publication validée pour produire une analyse cohérente.
6. Prévoir une ingestion rejouable sans doublons et la prise en compte des corrections.
7. Ne pas reconstruire artificiellement un historique absent du DW.
8. Limiter les données personnelles au strict nécessaire ; pseudonymiser les identifiants utilisateurs.

## Projection

Cible pressentie : utilisateurs actifs quotidiens par logiciel et périmètre, seulement si les données le permettent. Définir si J+7 désigne le point du septième jour ou toute la trajectoire des sept jours suivants. Évaluer les prévisions sur le passé en respectant la disponibilité réelle des observations, sans fuite de données futures.
