"""Generate fictional data in a NEW SQLite database, never modify a real source."""

import sqlite3
from pathlib import Path

path = Path("data/demo.sqlite")
path.parent.mkdir(exist_ok=True)
with path.open("xb"):
    pass
with sqlite3.connect(path) as conn:
    conn.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE software (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL);
    CREATE TABLE daily_usage (
        id INTEGER PRIMARY KEY, software_id INTEGER NOT NULL REFERENCES software(id),
        observed_on DATE NOT NULL, active_users INTEGER NOT NULL
    );
    INSERT INTO software VALUES (1, 'Produit fictif');
    INSERT INTO daily_usage VALUES (1, 1, '2026-09-14', 42), (2, 1, '2026-09-15', 46);
    CREATE VIEW usage_overview AS SELECT observed_on, active_users FROM daily_usage;
    """)
print(f"Base fictive créée : {path}")
