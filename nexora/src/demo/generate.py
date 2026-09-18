"""A fictional DW for scanner QA, not a reproduction of the Flexera schema."""

import argparse
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE organizations (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, country VARCHAR(2) NOT NULL);
CREATE TABLE software (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, category VARCHAR(40) NOT NULL);
CREATE TABLE users (id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id), pseudonym VARCHAR(30) NOT NULL UNIQUE);
CREATE TABLE machines (id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id), user_id INTEGER NOT NULL REFERENCES users(id), hostname VARCHAR(40) NOT NULL UNIQUE);
CREATE TABLE installations (id INTEGER PRIMARY KEY, machine_id INTEGER NOT NULL REFERENCES machines(id), software_id INTEGER NOT NULL REFERENCES software(id), installed_on DATE NOT NULL, UNIQUE(machine_id,software_id));
CREATE TABLE collection_coverage (organization_id INTEGER NOT NULL REFERENCES organizations(id), observed_on DATE NOT NULL, status VARCHAR(20) NOT NULL CHECK(status IN ('complete','missing')), PRIMARY KEY(organization_id,observed_on));
CREATE TABLE usage_observations (id INTEGER PRIMARY KEY, installation_id INTEGER NOT NULL REFERENCES installations(id), observed_on DATE NOT NULL, active_minutes INTEGER NOT NULL CHECK(active_minutes > 0), UNIQUE(installation_id,observed_on));
CREATE INDEX ix_usage_date ON usage_observations(observed_on);
CREATE INDEX ix_usage_installation ON usage_observations(installation_id);
CREATE VIEW installation_inventory AS
 SELECT i.id AS installation_id, i.installed_on, s.id AS software_id, s.name AS software_name,
 m.id AS machine_id, u.pseudonym AS user_pseudonym, o.id AS organization_id, o.name AS organization_name
 FROM installations i JOIN software s ON s.id=i.software_id JOIN machines m ON m.id=i.machine_id
 JOIN users u ON u.id=m.user_id JOIN organizations o ON o.id=m.organization_id;
CREATE VIEW observed_usage AS
 SELECT u.id AS observation_id, u.observed_on, u.active_minutes, i.software_id,
 i.machine_id, m.user_id, m.organization_id
 FROM usage_observations u JOIN installations i ON i.id=u.installation_id
 JOIN machines m ON m.id=i.machine_id;
"""


def generate(path: Path, days=90, users=240, seed=42):
    if not 7 <= days <= 366 or not 12 <= users <= 10000:
        raise ValueError("Prévoir 7 à 366 jours et 12 à 10 000 utilisateurs.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    rng = random.Random(seed)
    start = date(2026, 6, 20)
    names = [
        "Atlas Notes",
        "Prisme Studio",
        "Orbite Analyse",
        "Mosaïque Plan",
        "Pixel Bureau",
        "Sillage Outils",
    ]
    try:
        with sqlite3.connect(path) as db:
            db.executescript(DDL)
            db.executemany(
                "INSERT INTO organizations VALUES (?,?,?)",
                [
                    (1, "Entité A — fictive", "FR"),
                    (2, "Entité B — fictive", "DE"),
                    (3, "Entité C — fictive", "ES"),
                    (4, "Entité D — fictive", "GB"),
                ],
            )
            db.executemany(
                "INSERT INTO software VALUES (?,?,?)",
                [
                    (i + 1, name, "Collaboration" if i % 2 == 0 else "Analyse")
                    for i, name in enumerate(names)
                ],
            )
            installs = []
            for user in range(1, users + 1):
                org = (user - 1) % 4 + 1
                db.execute("INSERT INTO users VALUES (?,?,?)", (user, org, f"synthetic-{user:05d}"))
                db.execute(
                    "INSERT INTO machines VALUES (?,?,?,?)",
                    (user, org, user, f"demo-host-{user:05d}"),
                )
                for software in rng.sample(range(1, 7), 3):
                    installed = (
                        start + timedelta(days=30) if software == 4 else start - timedelta(days=20)
                    )
                    ident = len(installs) + 1
                    installs.append((ident, user, software, org, installed))
                    db.execute(
                        "INSERT INTO installations VALUES (?,?,?,?)",
                        (ident, user, software, installed.isoformat()),
                    )
            observations = []
            for offset in range(days):
                day = start + timedelta(days=offset)
                missing = 2 if offset in (20, 21, 55) else None
                for org in range(1, 5):
                    db.execute(
                        "INSERT INTO collection_coverage VALUES (?,?,?)",
                        (org, day.isoformat(), "missing" if org == missing else "complete"),
                    )
                for ident, user, software, org, installed in installs:
                    if org == missing or day < installed:
                        continue
                    probability = {
                        1: 0.65,
                        2: 0.2 + 0.5 * offset / max(days - 1, 1),
                        3: 0.7 - 0.4 * offset / max(days - 1, 1),
                        4: 0.45,
                        5: 0.04,
                        6: 0.3,
                    }[software]
                    probability *= 0.2 if day.weekday() >= 5 else 1
                    # A cohort with observed coverage but no recorded activity.
                    if user % 17 == 0 or rng.random() >= probability:
                        continue
                    observations.append(
                        (len(observations) + 1, ident, day.isoformat(), rng.randint(5, 300))
                    )
            db.executemany("INSERT INTO usage_observations VALUES (?,?,?,?)", observations)
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
            counts = {
                table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in [
                    "organizations",
                    "software",
                    "users",
                    "machines",
                    "installations",
                    "collection_coverage",
                    "usage_observations",
                ]
            }
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {
        "synthetic": True,
        "seed": seed,
        "start": start.isoformat(),
        "end": (start + timedelta(days=days - 1)).isoformat(),
        "rows": counts,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Créer un DW fictif, sans écraser un fichier existant"
    )
    parser.add_argument("--output", type=Path, default=Path("data/enterprise.sqlite"))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--users", type=int, default=240)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.days, args.users, args.seed), indent=2))


if __name__ == "__main__":
    main()
