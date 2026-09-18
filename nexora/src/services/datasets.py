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
POINTER = "bronze/demo-analytics/current.json"


def load_dataset(client, bucket, manifest_key):
    manifest = json.loads(client.get_object(Bucket=bucket, Key=manifest_key)["Body"].read())
    objects = {o["name"]: o for o in manifest["objects"]}
    if set(objects) != TABLES or any(o["truncated"] for o in objects.values()):
        raise ValueError("La démo analytique nécessite un snapshot complet")
    tables = {}
    prefix = manifest_key.removesuffix("manifest.json")
    for name, obj in objects.items():
        if not obj["key"].startswith(prefix) or obj["bytes"] > 100_000_000:
            raise ValueError("Objet de démonstration invalide")
        content = client.get_object(Bucket=bucket, Key=obj["key"])["Body"].read()
        table = pq.read_table(io.BytesIO(content))
        if table.num_rows != obj["rows"]:
            raise ValueError("Snapshot incomplet")
        tables[name] = table.to_pylist()
    return UsageDataset(tables, manifest)


def ensure_demo(source_url, client=None, bucket=None):
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    try:
        pointer = json.loads(client.get_object(Bucket=bucket, Key=POINTER)["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
            raise
        pointer = None
    if pointer is None:
        with source_connection(source_url) as conn:
            objects = [
                o for o in scan(conn)["objects"] if o["kind"] == "table" and o["name"] in TABLES
            ]
            if {o["name"] for o in objects} != TABLES:
                raise ValueError("Schéma de démonstration incomplet")
            selection = Selection.model_validate(
                {
                    "source_label": "demo-analytics",
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
        key = result["manifest"]["storage"]["prefix"] + "/manifest.json"
        dataset = load_dataset(client, bucket, key)
        client.put_object(
            Bucket=bucket,
            Key=POINTER,
            Body=json.dumps({"manifest_key": key}).encode(),
            ContentType="application/json",
        )
        return dataset
    return load_dataset(client, bucket, pointer["manifest_key"])


def list_extractions(client=None, bucket=None):
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    candidates = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="bronze/"):
        candidates.extend(
            o for o in page.get("Contents", []) if o["Key"].endswith("/manifest.json")
        )
    results = []
    for obj in sorted(candidates, key=lambda o: o["LastModified"], reverse=True)[:50]:
        manifest = json.loads(client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
        results.append(
            {
                "source": manifest["source_label"],
                "published_at": manifest.get("published_at", manifest["completed_at"]),
                "tables": len(manifest["objects"]),
                "rows": sum(o["rows"] for o in manifest["objects"]),
                "truncated": any(o["truncated"] for o in manifest["objects"]),
                "location": f"s3://{bucket}/{obj['Key'].removesuffix('/manifest.json')}",
            }
        )
    return results
