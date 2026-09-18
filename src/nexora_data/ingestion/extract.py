"""Explicit selections, bounded row batches and atomic run publication."""

import hashlib
import json
import shutil
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import MetaData, Table, inspect, select

from .selection import Selection


def arrow_type(sql_type):
    try:
        python_type = sql_type.python_type
    except (NotImplementedError, AttributeError):
        raise ValueError("Type SQL non pris en charge pour Parquet.") from None
    if python_type is Decimal:
        precision, scale = getattr(sql_type, "precision", None), getattr(sql_type, "scale", None)
        if precision is None or scale is None or not 1 <= precision <= 76:
            raise ValueError("Décimal sans précision/échelle exploitable : utiliser une vue CAST.")
        return (pa.decimal128 if precision <= 38 else pa.decimal256)(precision, scale)
    if python_type is datetime:
        return pa.timestamp("us", tz="UTC" if getattr(sql_type, "timezone", False) else None)
    mapping = {
        str: pa.string(),
        int: pa.int64(),
        float: pa.float64(),
        bool: pa.bool_(),
        bytes: pa.binary(),
        date: pa.date32(),
        time: pa.time64("us"),
        UUID: pa.string(),
    }
    if python_type not in mapping:
        raise ValueError("Type SQL non pris en charge : sélectionner une vue avec CAST explicite.")
    return mapping[python_type]


def extract(conn, selection: Selection, output: Path):
    inspector = inspect(conn)
    # Validate every object and every Arrow type before reading business data.
    prepared = []
    available_schemas = inspector.get_schema_names()
    for item in selection.objects:
        if item.schema_name not in available_schemas:
            raise ValueError("Schéma absent ou inaccessible.")
        names = inspector.get_table_names(schema=item.schema_name) + inspector.get_view_names(
            schema=item.schema_name
        )
        if item.name not in names:
            raise ValueError("Table/vue absente ou inaccessible.")
        table = Table(
            item.name, MetaData(), schema=item.schema_name, autoload_with=conn, resolve_fks=False
        )
        if any(c not in table.c for c in item.columns):
            raise ValueError("Colonne absente de la table/vue sélectionnée.")
        columns = [table.c[c] for c in item.columns]
        arrow_schema = pa.schema(
            [pa.field(c.name, arrow_type(c.type), nullable=c.nullable) for c in columns]
        )
        prepared.append((item, columns, arrow_schema))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    staging, final = output / f".{run_id}.partial", output / run_id
    staging.mkdir()
    manifest = {
        "manifest_version": 1,
        "run_id": run_id,
        "source_label": selection.source_label,
        "dialect": conn.dialect.name,
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "full_or_limited_snapshot",
        "cross_object_snapshot_guaranteed": False,
        "objects": [],
    }
    try:
        for index, (item, columns, arrow_schema) in enumerate(prepared):
            filename = f"object-{index:04d}.parquet"
            path = staging / filename
            statement = select(*columns)
            if item.row_limit is not None:
                statement = statement.limit(item.row_limit + 1)
            result = conn.execution_options(yield_per=selection.batch_size).execute(statement)
            count, truncated = 0, False
            try:
                with pq.ParquetWriter(path, arrow_schema, compression="zstd") as writer:
                    while rows := result.fetchmany(selection.batch_size):
                        remaining = len(rows) if item.row_limit is None else item.row_limit - count
                        if len(rows) > remaining:
                            truncated = True
                        rows = rows[:remaining]
                        if rows:
                            records = [
                                {
                                    c.name: str(v) if isinstance(v, UUID) else v
                                    for c, v in zip(columns, row, strict=True)
                                }
                                for row in rows
                            ]
                            writer.write_table(pa.Table.from_pylist(records, schema=arrow_schema))
                            count += len(rows)
                        if truncated:
                            break
            finally:
                result.close()
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest["objects"].append(
                {
                    **item.model_dump(by_alias=True),
                    "file": filename,
                    "rows": count,
                    "truncated": truncated,
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                    "arrow_schema": str(arrow_schema),
                }
            )
        manifest["completed_at"] = datetime.now(UTC).isoformat()
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return final
