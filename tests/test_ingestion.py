import json
import sqlite3
from decimal import Decimal

import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError

from nexora.src.cli import main
from nexora.src.ingestion.catalog import scan
from nexora.src.ingestion.connection import source_connection
from nexora.src.ingestion.extract import extract
from nexora.src.ingestion.selection import Selection


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE software (id INTEGER PRIMARY KEY, name TEXT)")
        conn.exec_driver_sql(
            "CREATE TABLE usage (id INTEGER PRIMARY KEY, software_id INTEGER "
            "REFERENCES software(id), amount NUMERIC(12,2), day DATE, secret TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO software VALUES (1, 'Example')")
        conn.exec_driver_sql(
            "INSERT INTO usage VALUES (1,1,NULL,'2026-09-01','private'), "
            "(2,1,12.34,'2026-09-02','private'), (3,1,56.78,NULL,'private')"
        )
        conn.exec_driver_sql("CREATE VIEW usage_view AS SELECT id, amount FROM usage")
        conn.exec_driver_sql("CREATE TABLE empty (id INTEGER, amount NUMERIC(12,2))")
        conn.exec_driver_sql('CREATE TABLE "odd; name" ("select" INTEGER)')
        conn.exec_driver_sql('INSERT INTO "odd; name" VALUES (9)')
    engine.dispose()
    monkeypatch.setenv("NEXORA_SOURCE_URL", f"sqlite:///{path}")
    return path


def selection(name="usage", columns=None, limit=10000):
    return Selection.model_validate(
        {
            "source_label": "fixture",
            "batch_size": 1,
            "objects": [
                {
                    "schema": "main",
                    "name": name,
                    "columns": columns or ["id", "amount", "day"],
                    "row_limit": limit,
                }
            ],
        }
    )


def test_scan_only_metadata(source):
    with source_connection() as conn:

        def metadata_only(action, name, column, database, trigger):
            if action == sqlite3.SQLITE_READ and name in {
                "usage",
                "software",
                "empty",
                "odd; name",
            }:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.connection.driver_connection.set_authorizer(metadata_only)
        statements = []
        event.listen(
            conn, "before_cursor_execute", lambda c, cu, sql, p, ctx, many: statements.append(sql)
        )
        catalog = scan(conn)
    obj = next(x for x in catalog["objects"] if x["name"] == "usage")
    assert obj["primary_key"]["constrained_columns"] == ["id"]
    assert obj["foreign_keys"][0]["referred_table"] == "software"
    assert any(x["kind"] == "view" for x in catalog["objects"])
    assert "private" not in json.dumps(catalog)
    assert obj["columns"][2]["sql_type"] == "NUMERIC(12, 2)"


def test_batches_nulls_decimal_dates_and_projection(source, tmp_path):
    with source_connection() as conn:
        run = extract(conn, selection(), tmp_path / "bronze")
    table = pq.read_table(run / "object-0000.parquet")
    assert table.column_names == ["id", "amount", "day"]
    assert table["amount"].to_pylist() == [None, Decimal("12.34"), Decimal("56.78")]
    assert str(table["day"].type) == "date32[day]"
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["objects"][0]["rows"] == 3
    assert manifest["objects"][0]["truncated"] is False
    assert len(manifest["objects"][0]["sha256"]) == 64
    assert "source.sqlite" not in json.dumps(manifest)


@pytest.mark.parametrize("limit, truncated", [(2, True), (3, False), (4, False), (None, False)])
def test_limits(source, tmp_path, limit, truncated):
    with source_connection() as conn:
        run = extract(conn, selection(limit=limit), tmp_path / "bronze")
    obj = json.loads((run / "manifest.json").read_text())["objects"][0]
    assert obj["rows"] == min(limit or 3, 3)
    assert obj["truncated"] is truncated


@pytest.mark.parametrize(
    "name, columns, count",
    [
        ("empty", ["id", "amount"], 0),
        ("usage_view", ["id", "amount"], 3),
        ("odd; name", ["select"], 1),
    ],
)
def test_empty_views_and_quoted_identifiers(source, tmp_path, name, columns, count):
    with source_connection() as conn:
        run = extract(conn, selection(name, columns), tmp_path / "bronze")
    table = pq.read_table(run / "object-0000.parquet")
    assert table.num_rows == count
    assert table.column_names == columns


def test_read_only(source):
    with source_connection() as conn, pytest.raises(OperationalError):
        conn.exec_driver_sql("DELETE FROM usage")


def test_invalid_selection_and_missing_objects(source, tmp_path):
    with pytest.raises(ValueError):
        selection(columns=["id", "id"])
    with source_connection() as conn, pytest.raises(ValueError):
        extract(conn, selection(columns=["missing"]), tmp_path / "bronze")
    assert not (tmp_path / "bronze").exists()


def test_failure_does_not_publish_partial_run(source, tmp_path, monkeypatch):
    import nexora.src.ingestion.extract as module

    def fail(*args, **kwargs):
        raise RuntimeError("write failure")

    monkeypatch.setattr(module.pq, "ParquetWriter", fail)
    with source_connection() as conn, pytest.raises(RuntimeError):
        extract(conn, selection(), tmp_path / "bronze")
    assert list((tmp_path / "bronze").iterdir()) == []


def test_cli_and_no_catalog_overwrite(source, tmp_path, capsys):
    catalog = tmp_path / "catalog.json"
    assert main(["scan", "--output", str(catalog)]) == 0
    original = catalog.read_bytes()
    assert main(["scan", "--output", str(catalog)]) == 1
    assert catalog.read_bytes() == original
    config = tmp_path / "selection.json"
    config.write_text(selection().model_dump_json(by_alias=True))
    assert main(["extract", "--selection", str(config), "--output", str(tmp_path / "bronze")]) == 0
    assert "private" not in capsys.readouterr().err


def test_failure_hides_connection_details(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(
        "NEXORA_SOURCE_URL", "postgresql+nonexistent://user:TOPSECRET@private-host/db"
    )
    assert main(["scan", "--output", str(tmp_path / "catalog.json")]) == 1
    output = capsys.readouterr()
    assert "TOPSECRET" not in output.err
    assert "private-host" not in output.err


def test_missing_sqlite_not_created(tmp_path, monkeypatch):
    path = tmp_path / "nonexistent.sqlite"
    monkeypatch.setenv("NEXORA_SOURCE_URL", f"sqlite:///{path}")
    with pytest.raises(ValueError), source_connection():
        pass
    assert not path.exists()
