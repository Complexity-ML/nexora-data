import hashlib
import io
import json

import boto3
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

from nexora.src.cli import main
from nexora.src.demo.generate import generate
from nexora.src.ingestion.connection import source_connection
from nexora.src.ingestion.selection import Selection
from nexora.src.storage.minio import publish


@pytest.fixture
def setup(tmp_path, monkeypatch):
    database = tmp_path / "source.sqlite"
    generate(database, days=7, users=12)
    monkeypatch.setenv("NEXORA_SOURCE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("NEXORA_S3_ENDPOINT", "https://s3.amazonaws.com")
    monkeypatch.setenv("NEXORA_S3_ACCESS_KEY", "testing")
    monkeypatch.setenv("NEXORA_S3_SECRET_KEY", "testing")
    monkeypatch.setenv("NEXORA_S3_BUCKET", "nexora-test")
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        client.create_bucket(Bucket="nexora-test")
        yield (
            client,
            Selection.model_validate(
                {
                    "source_label": "demo",
                    "objects": [
                        {"schema": "main", "name": "organizations", "columns": ["id", "name"]}
                    ],
                }
            ),
        )


def test_publish_manifest_last_and_parquet_readback(setup, monkeypatch):
    client, selection = setup
    order = []
    original = client.put_object

    def record(**kwargs):
        order.append(kwargs["Key"])
        return original(**kwargs)

    monkeypatch.setattr(client, "put_object", record)
    with source_connection() as conn:
        result = publish(conn, selection, client=client, bucket="nexora-test")
    assert order[-1].endswith("manifest.json")
    assert result["directory"].startswith("s3://nexora-test/bronze/demo/")
    manifest = json.loads(client.get_object(Bucket="nexora-test", Key=order[-1])["Body"].read())
    obj = manifest["objects"][0]
    content = client.get_object(Bucket="nexora-test", Key=obj["key"])["Body"].read()
    assert hashlib.sha256(content).hexdigest() == obj["sha256"]
    assert pq.read_table(io.BytesIO(content)).num_rows == 4
    assert "testing" not in json.dumps(manifest)


def test_failed_upload_leaves_no_published_run(setup, monkeypatch):
    client, selection = setup

    def fail(**kwargs):
        raise RuntimeError("failure")

    monkeypatch.setattr(client, "head_object", fail)
    with source_connection() as conn, pytest.raises(RuntimeError):
        publish(conn, selection, client=client, bucket="nexora-test")
    assert client.list_objects_v2(Bucket="nexora-test").get("Contents", []) == []


def test_cli_defaults_to_minio(setup, tmp_path, capsys):
    client, selection = setup
    config = tmp_path / "selection.json"
    config.write_text(selection.model_dump_json(by_alias=True))
    assert main(["extract", "--selection", str(config)]) == 0
    assert "s3://nexora-test/" in capsys.readouterr().out
    assert len(client.list_objects_v2(Bucket="nexora-test")["Contents"]) == 2
