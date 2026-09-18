import io
import json
import sqlite3

import boto3
import pyarrow.parquet as pq
from moto import mock_aws

from nexora.src.ingestion.connection import source_connection
from nexora.src.ingestion.selection import Selection
from nexora.src.services.datasets import delete_extraction
from nexora.src.storage.refresh import refresh


def test_only_changed_blocks_downloaded_and_old_versions_preserved(tmp_path):
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)")
        db.executemany(
            "INSERT INTO items VALUES (?,?)", [(1, "one"), (10001, "two"), (20001, "three")]
        )
    selection = Selection.model_validate(
        {
            "source_label": "test-dw",
            "objects": [
                {"schema": "main", "name": "items", "columns": ["id", "value"], "row_limit": None}
            ],
        }
    )
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
        )
        client.create_bucket(Bucket="refresh-tests")

        def run():
            with source_connection(f"sqlite:///{path}") as conn:
                return refresh(conn, selection, client, "refresh-tests")["manifest"]

        first = run()
        assert first["refresh"]["downloaded_rows"] == 3
        second = run()
        assert second["refresh"]["downloaded_rows"] == 0
        assert second["refresh"]["reused_blocks"] == 3
        with sqlite3.connect(path) as db:
            db.execute("UPDATE items SET value='changed' WHERE id=1")
            db.execute("DELETE FROM items WHERE id=10001")
            db.execute("INSERT INTO items VALUES (30001,'new')")
        third = run()
        assert third["refresh"]["downloaded_rows"] == 2
        assert third["refresh"]["reused_blocks"] == 1
        assert third["refresh"]["removed_blocks"] == 1

        def rows(manifest):
            return sorted(
                [
                    r
                    for p in manifest["objects"][0]["parts"]
                    for r in pq.read_table(
                        io.BytesIO(
                            client.get_object(Bucket="refresh-tests", Key=p["key"])["Body"].read()
                        )
                    ).to_pylist()
                ],
                key=lambda r: r["id"],
            )

        assert rows(first) == [
            {"id": 1, "value": "one"},
            {"id": 10001, "value": "two"},
            {"id": 20001, "value": "three"},
        ]
        assert rows(third) == [
            {"id": 1, "value": "changed"},
            {"id": 20001, "value": "three"},
            {"id": 30001, "value": "new"},
        ]
        delete_extraction(first["storage"]["prefix"] + "/manifest.json", client, "refresh-tests")
        assert len(rows(second)) == 3 and len(rows(third)) == 3
        assert (
            json.loads(
                client.get_object(Bucket="refresh-tests", Key="bronze/test-dw/latest-full.json")[
                    "Body"
                ].read()
            )["manifest_key"]
            == third["storage"]["prefix"] + "/manifest.json"
        )


def test_deleted_rows_without_keys_and_failed_publication(tmp_path, monkeypatch):
    import pytest

    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE raw(value TEXT)")
        db.executemany("INSERT INTO raw VALUES (?)", [("same",), ("same",), (None,)])
        db.execute("CREATE VIEW rows_view AS SELECT value FROM raw")
    selection = Selection.model_validate(
        {
            "source_label": "views",
            "objects": [
                {"schema": "main", "name": "rows_view", "columns": ["value"], "row_limit": None}
            ],
        }
    )
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
        )
        client.create_bucket(Bucket="refresh-tests")

        def run():
            with source_connection(f"sqlite:///{path}") as conn:
                return refresh(conn, selection, client, "refresh-tests")["manifest"]

        first = run()
        assert run()["refresh"]["downloaded_rows"] == 0
        with sqlite3.connect(path) as db:
            db.execute("DELETE FROM raw WHERE rowid=1")
        second = run()
        assert second["objects"][0]["rows"] == 2
        assert second["refresh"]["downloaded_rows"] == 1
        pointer = client.get_object(Bucket="refresh-tests", Key="bronze/views/latest-full.json")[
            "Body"
        ].read()
        original = client.put_object

        def fail_manifest(**kwargs):
            if kwargs["Key"].endswith("/manifest.json"):
                raise RuntimeError("simulated publication failure")
            return original(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(client, "put_object", fail_manifest)
            with pytest.raises(RuntimeError):
                run()
        assert (
            client.get_object(Bucket="refresh-tests", Key="bronze/views/latest-full.json")[
                "Body"
            ].read()
            == pointer
        )
        assert client.head_object(
            Bucket="refresh-tests", Key=first["objects"][0]["parts"][0]["key"]
        )
        with sqlite3.connect(path) as db:
            db.execute("DELETE FROM raw")
        empty = run()
        assert empty["objects"][0]["rows"] == 0
        assert empty["objects"][0]["parts"] == []
        assert empty["refresh"]["downloaded_rows"] == 0
