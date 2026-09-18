import json
import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import boto3
from botocore.config import Config

from ..ingestion.extract import extract


def client_from_env():
    required = [
        "NEXORA_S3_ENDPOINT",
        "NEXORA_S3_ACCESS_KEY",
        "NEXORA_S3_SECRET_KEY",
        "NEXORA_S3_BUCKET",
    ]
    if any(not os.environ.get(key) for key in required):
        raise ValueError("Configuration MinIO incomplète.")
    return boto3.client(
        "s3",
        endpoint_url=os.environ["NEXORA_S3_ENDPOINT"],
        aws_access_key_id=os.environ["NEXORA_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["NEXORA_S3_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 3},
        ),
    )


def publish(conn, selection, *, client=None, bucket=None):
    client = client if client is not None else client_from_env()
    bucket = bucket or os.environ["NEXORA_S3_BUCKET"]
    client.head_bucket(Bucket=bucket)
    # Parquet needs a seekable staging file; this directory is removed on success/failure.
    with TemporaryDirectory(prefix="nexora-parquet-") as staging:
        run = extract(conn, selection, Path(staging))
        manifest = json.loads((run / "manifest.json").read_text())
        prefix = f"bronze/{selection.source_label}/{manifest['run_id']}"
        attempted = []
        try:
            for obj in manifest["objects"]:
                key = f"{prefix}/{obj['file']}"
                attempted.append(key)
                client.upload_file(
                    str(run / obj["file"]),
                    bucket,
                    key,
                    ExtraArgs={
                        "ContentType": "application/vnd.apache.parquet",
                        "Metadata": {"sha256": obj["sha256"]},
                    },
                )
                head = client.head_object(Bucket=bucket, Key=key)
                if (
                    head["ContentLength"] != obj["bytes"]
                    or head["Metadata"].get("sha256") != obj["sha256"]
                ):
                    raise ValueError("Objet S3 incomplet.")
                obj["key"] = key
            manifest["storage"] = {"type": "s3", "bucket": bucket, "prefix": prefix}
            manifest["published_at"] = datetime.now(UTC).isoformat()
            # The manifest is the publication marker and MUST be written last.
            key = f"{prefix}/manifest.json"
            attempted.append(key)
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(manifest).encode(),
                ContentType="application/json",
            )
        except Exception:  # noqa: BLE001 — cleanup must not mask the publication failure
            for key in reversed(attempted):
                # A storage outage can leave unreferenced objects; no manifest means unpublished.
                with suppress(Exception):
                    client.delete_object(Bucket=bucket, Key=key)
            raise
    return {"ok": True, "manifest": manifest, "directory": f"s3://{bucket}/{prefix}"}
