"""Read-only SQL comparison followed by immutable changed-block publication."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from sqlalchemy import String, bindparam, column, text

from ..ingestion.extract import arrow_type
from ..ingestion.fingerprints import queries
from .coordination import storage_lock


def refresh(conn, selection, client, bucket):
    # The source transaction is stable across fingerprinting and selective reads.
    if conn.dialect.name == "sqlite":
        if not conn.connection.driver_connection.in_transaction:
            conn.exec_driver_sql("BEGIN")
    elif conn.dialect.name == "postgresql":
        if conn.get_isolation_level() != "REPEATABLE READ":
            raise ValueError("Actualisation requiert REPEATABLE READ")
    elif conn.dialect.name == "mssql":
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
    run = str(uuid4())
    prefix = f"bronze/{selection.source_label}/{run}"
    pointer = f"bronze/{selection.source_label}/latest-full.json"
    try:
        previous_key = json.loads(client.get_object(Bucket=bucket, Key=pointer)["Body"].read())[
            "manifest_key"
        ]
        previous = json.loads(client.get_object(Bucket=bucket, Key=previous_key)["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
            raise
        previous = {"objects": []}
    old = {(o["schema"], o["name"]): o for o in previous["objects"]}
    manifest = {
        "manifest_version": 2,
        "run_id": run,
        "source_label": selection.source_label,
        "dialect": conn.dialect.name,
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "sql_block_comparison",
        "cross_object_snapshot_guaranteed": True,
        "objects": [],
        "storage": {"type": "s3", "bucket": bucket, "prefix": prefix},
        "refresh": {
            "downloaded_rows": 0,
            "reused_blocks": 0,
            "changed_blocks": 0,
            "removed_blocks": 0,
        },
    }
    with TemporaryDirectory(prefix="nexora-refresh-") as tmp:
        for index, item in enumerate(selection.objects):
            spec = queries(conn, item)
            fingerprints = {
                str(r.block_id): {"rows": r.row_count, "digest": r.digest}
                for r in conn.execute(text(spec["summary"]))
            }
            prior = old.get((item.schema_name, item.name), {})
            oldparts = (
                {p["block"]: p for p in prior.get("parts", [])}
                if prior.get("signature") == spec["signature"]
                else {}
            )
            changed = []
            parts = []
            for block, fp in fingerprints.items():
                existing = oldparts.get(block)
                if (
                    existing
                    and existing["digest"] == fp["digest"]
                    and existing["rows"] == fp["rows"]
                ):
                    client.head_object(Bucket=bucket, Key=existing["key"])
                    parts.append(existing)
                    manifest["refresh"]["reused_blocks"] += 1
                else:
                    changed.append(block)
            manifest["refresh"]["removed_blocks"] += len(set(oldparts) - set(fingerprints))
            schema = pa.schema(
                [pa.field(c.name, arrow_type(c.type), nullable=c.nullable) for c in spec["columns"]]
            )
            if changed:
                # SQL returns business rows only for changed blocks, in bounded batches.
                stmt = (
                    text(
                        f"SELECT {spec['block']} AS nexora_block_id,{','.join(spec['names'])} FROM {spec['source']} WHERE CAST({spec['block']} AS VARCHAR(64)) IN :blocks ORDER BY {spec['block']}"
                    )
                    .bindparams(bindparam("blocks", expanding=True))
                    .columns(column("nexora_block_id", String), *spec["columns"])
                )
                # Bound parameter counts for SQL Server as well.
                for offset in range(0, len(changed), 500):
                    result = conn.execution_options(yield_per=selection.batch_size).execute(
                        stmt, {"blocks": changed[offset : offset + 500]}
                    )
                    writer = None
                    current = None
                    count = 0
                    path = Path(tmp) / f"part-{index}.parquet"

                    def finish(writer, current, count, path, fingerprints, parts):
                        if writer is None:
                            return
                        writer.close()
                        fp = fingerprints[current]
                        if count != fp["rows"]:
                            raise ValueError("Source modifiée pendant la lecture")
                        with path.open("rb") as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        key = f"bronze/{selection.source_label}/blocks/{digest}.parquet"
                        client.upload_file(
                            str(path), bucket, key, ExtraArgs={"Metadata": {"sha256": digest}}
                        )
                        parts.append(
                            {
                                "block": current,
                                **fp,
                                "key": key,
                                "sha256": digest,
                                "bytes": path.stat().st_size,
                            }
                        )
                        manifest["refresh"]["downloaded_rows"] += count
                        manifest["refresh"]["changed_blocks"] += 1

                    try:
                        while rows := result.fetchmany(selection.batch_size):
                            records = []
                            for row in rows:
                                block = str(row[0])
                                if block != current:
                                    if records:
                                        writer.write_table(
                                            pa.Table.from_pylist(records, schema=schema)
                                        )
                                        records = []
                                    finish(writer, current, count, path, fingerprints, parts)
                                    current = block
                                    count = 0
                                    writer = pq.ParquetWriter(path, schema, compression="zstd")
                                records.append(
                                    {
                                        c.name: str(v) if isinstance(v, UUID) else v
                                        for c, v in zip(spec["columns"], row[1:], strict=True)
                                    }
                                )
                                count += 1
                            if records:
                                writer.write_table(pa.Table.from_pylist(records, schema=schema))
                        finish(writer, current, count, path, fingerprints, parts)
                    finally:
                        result.close()
                        if writer is not None:
                            writer.close()
            parts.sort(key=lambda p: p["block"])
            manifest["objects"].append(
                {
                    **item.model_dump(by_alias=True),
                    "rows": sum(p["rows"] for p in parts),
                    "truncated": False,
                    "parts": parts,
                    "signature": spec["signature"],
                    "arrow_schema": str(schema),
                    "bytes": sum(p["bytes"] for p in parts),
                }
            )
    manifest["completed_at"] = manifest["published_at"] = datetime.now(UTC).isoformat()
    key = prefix + "/manifest.json"
    # Writers/deletion are serialized; old manifests and referenced files stay immutable.
    with storage_lock:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(manifest).encode(),
            ContentType="application/json",
        )
        client.put_object(
            Bucket=bucket,
            Key=pointer,
            Body=json.dumps({"manifest_key": key}).encode(),
            ContentType="application/json",
        )
    return {"ok": True, "manifest": manifest, "directory": f"s3://{bucket}/{prefix}"}
