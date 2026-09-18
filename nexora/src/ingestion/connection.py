"""Connections never issue application writes; source permissions remain authoritative."""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url


@contextmanager
def source_connection(value=None):
    value = value or os.environ.get("NEXORA_SOURCE_URL")
    if not value:
        raise ValueError("Définir NEXORA_SOURCE_URL dans l’environnement.")
    url = make_url(value)
    if url.get_backend_name() not in {"sqlite", "postgresql", "mssql"}:
        raise ValueError("Moteurs préparés : SQLite, PostgreSQL, SQL Server.")
    if url.get_backend_name() == "sqlite":
        # Prevent a typo from creating a new source database.
        from pathlib import Path

        if not url.database or not Path(url.database).is_file():
            raise ValueError("La base SQLite source doit déjà exister.")
    engine = create_engine(url, echo=False, hide_parameters=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def read_only(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA query_only = ON")

    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '60s'")
            # Always rollback; SQL Server must use a SELECT-only database principal.
            yield conn
            conn.rollback()
    finally:
        engine.dispose()
