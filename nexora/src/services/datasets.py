"""Persist and load a full demo snapshot from MinIO, using one published manifest."""

import io
import json
import os

import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from ..analytics.usage import UsageDataset
from ..ingestion.catalog import scan
from ..ingestion.connection import source_connection
from ..ingestion.selection import Selection
from ..storage.minio import client_from_env, publish

TABLES = {
    "organizations",
    "software",
    "users",
    "machines",
    "installations",
    "collection_coverage",
    "usage_observations",
}
POINTER = "bronze/demo-enterprise/current.json"


def load_dataset(client, bucket, manifest_key):
    manifest = json.loads(client.get_object(Bucket=bucket, Key=manifest_key)["Body"].read())
    objects = {o["name"]: o for o in manifest["objects"]}
    if not TABLES.issubset(objects) or any(o["truncated"] for o in objects.values()):
        raise ValueError("La démo analytique nécessite un snapshot complet")
    tables = {}
    prefix = manifest_key.removesuffix("manifest.json")
    for name in TABLES:
        obj = objects[name]
        if not obj["key"].startswith(prefix) or obj["bytes"] > 100_000_000:
            raise ValueError("Objet de démonstration invalide")
        content = client.get_object(Bucket=bucket, Key=obj["key"])["Body"].read()
        table = pq.read_table(io.BytesIO(content))
        if table.num_rows != obj["rows"]:
            raise ValueError("Snapshot incomplet")
        tables[name] = table.to_pylist()
    return UsageDataset(tables, manifest)


def active_key(client, bucket):
    try:
        return json.loads(client.get_object(Bucket=bucket, Key=POINTER)["Body"].read())[
            "manifest_key"
        ]
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            return None
        raise


def activate_collection(result, client=None, bucket=None):
    manifest = result["manifest"]
    if manifest["source_label"] != "demo-enterprise" or any(
        o["truncated"] for o in manifest["objects"]
    ):
        return None
    if not TABLES.issubset({o["name"] for o in manifest["objects"]}):
        return None
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    key = manifest["storage"]["prefix"] + "/manifest.json"
    dataset = load_dataset(client, bucket, key)
    client.put_object(
        Bucket=bucket,
        Key=POINTER,
        Body=json.dumps({"manifest_key": key}).encode(),
        ContentType="application/json",
    )
    return dataset


def ensure_demo(source_url, client=None, bucket=None):
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    key = active_key(client, bucket)
    if key:
        return load_dataset(client, bucket, key)
    # Reuse an existing full collection of the same DW before producing another one.
    for run in list_extractions(client, bucket):
        if run["source"] == "demo-enterprise" and not run["truncated"]:
            manifest = json.loads(
                client.get_object(Bucket=bucket, Key=run["manifest_key"])["Body"].read()
            )
            dataset = activate_collection({"manifest": manifest}, client, bucket)
            if dataset is not None:
                return dataset
    with source_connection(source_url) as conn:
        objects = scan(conn)["objects"]
        selection = Selection.model_validate(
            {
                "source_label": "demo-enterprise",
                "objects": [
                    {
                        "schema": o["schema"],
                        "name": o["name"],
                        "columns": [c["name"] for c in o["columns"]],
                        "row_limit": None,
                    }
                    for o in objects
                ],
            }
        )
        result = publish(conn, selection, client=client, bucket=bucket)
    dataset = activate_collection(result, client, bucket)
    if dataset is None:
        raise ValueError("Le DW de démonstration ne contient pas les observations attendues")
    return dataset


class DatasetReader:
    def __init__(self, initial):
        from threading import Lock

        self.dataset = initial
        self.lock = Lock()

    def get(self):
        client = client_from_env()
        bucket = os.environ["NEXORA_S3_BUCKET"]
        with self.lock:
            key = active_key(client, bucket)
            if not key:
                raise ValueError("Aucune collecte analytique publiée")
            current = self.dataset.manifest["storage"]["prefix"] + "/manifest.json"
            if key != current:
                self.dataset = load_dataset(client, bucket, key)
            return self.dataset


def list_extractions(client=None, bucket=None):
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    candidates = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="bronze/"):
        candidates.extend(
            o for o in page.get("Contents", []) if o["Key"].endswith("/manifest.json")
        )
    current = active_key(client, bucket)
    results = []
    selected = sorted(candidates, key=lambda o: o["LastModified"], reverse=True)[:50]
    if current and not any(obj["Key"] == current for obj in selected):
        selected.append({"Key": current})
    for obj in selected:
        manifest = json.loads(client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
        results.append(
            {
                "source": manifest["source_label"],
                "manifest_key": obj["Key"],
                "active": obj["Key"] == current,
                "published_at": manifest.get("published_at", manifest["completed_at"]),
                "tables": len(manifest["objects"]),
                "rows": sum(o["rows"] for o in manifest["objects"]),
                "truncated": any(o["truncated"] for o in manifest["objects"]),
                "location": f"s3://{bucket}/{obj['Key'].removesuffix('/manifest.json')}",
            }
        )
    return results


def delete_extraction(manifest_key, client=None, bucket=None):
    """Delete exactly one published extraction; never modify the SQL source."""
    import re

    if not isinstance(manifest_key, str) or not re.fullmatch(
        r"bronze/[A-Za-z0-9_-]+/[0-9a-fA-F-]{36}/manifest\.json", manifest_key
    ):
        raise ValueError("Extraction invalide")
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    manifest = json.loads(client.get_object(Bucket=bucket, Key=manifest_key)["Body"].read())
    prefix = manifest_key.removesuffix("manifest.json")
    if manifest["storage"]["prefix"] + "/" != prefix:
        raise ValueError("Provenance invalide")
    # Remove references before any data, so a partial failure cannot expose stale analysis.
    pointer_key = "/".join(manifest_key.split("/")[:2]) + "/current.json"
    for pointer in {POINTER, pointer_key}:
        try:
            value = json.loads(client.get_object(Bucket=bucket, Key=pointer)["Body"].read())
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                continue
            raise
        if value.get("manifest_key") == manifest_key:
            client.delete_object(Bucket=bucket, Key=pointer)
    keys = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []) if o["Key"] != manifest_key)
    for offset in range(0, len(keys), 1000):
        result = client.delete_objects(
            Bucket=bucket,
            Delete={
                "Objects": [{"Key": key} for key in keys[offset : offset + 1000]],
                "Quiet": True,
            },
        )
        if result.get("Errors"):
            raise RuntimeError("Suppression incomplète ; réessayez.")
    # Keep the manifest until the files are removed, allowing retries after failure.
    client.delete_object(Bucket=bucket, Key=manifest_key)
    return len(keys)
