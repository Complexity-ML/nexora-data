"""Database-side ordered block fingerprints. Only summaries cross the connection."""

import hashlib
import json

from sqlalchemy import MetaData, Table

from .extract import arrow_type

BLOCK_SIZE = 10000


def sqlite_functions(conn):
    raw = conn.connection.driver_connection

    def digest(*values):
        encoded = json.dumps(
            [{"blob": v.hex()} if isinstance(v, bytes) else v for v in values],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.md5(encoded.encode(), usedforsecurity=False).hexdigest()

    class OrderedHash:
        def __init__(self):
            self.values = []

        def step(self, value):
            self.values.append(value)

        def finalize(self):
            return hashlib.md5(
                "".join(sorted(self.values)).encode(), usedforsecurity=False
            ).hexdigest()

    raw.create_function("nexora_hash", -1, digest, deterministic=True)
    raw.create_aggregate("nexora_block_hash", 1, OrderedHash)


def queries(conn, item):
    table = Table(
        item.name, MetaData(), schema=item.schema_name, autoload_with=conn, resolve_fks=False
    )
    columns = [table.c[name] for name in item.columns]
    for column in columns:
        arrow_type(column.type)
    q = conn.dialect.identifier_preparer.quote
    source = f"{q(item.schema_name)}.{q(item.name)}"
    names = [q(c.name) for c in columns]
    keys = [q(c.name) for c in table.primary_key.columns] or names
    dialect = conn.dialect.name

    def hash_expression(fields):
        if dialect == "sqlite":
            return "nexora_hash(" + ",".join(fields) + ")"
        if dialect == "postgresql":
            return "md5(json_build_array(" + ",".join(fields) + ")::text)"
        if dialect == "mssql":
            projection = ",".join(f"{f} AS {q('c' + str(i))}" for i, f in enumerate(fields))
            return (
                "LOWER(CONVERT(varchar(64),HASHBYTES('SHA2_256',(SELECT "
                + projection
                + " FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES)),2))"
            )
        raise ValueError("Comparaison SQL indisponible pour ce moteur")

    if dialect == "sqlite":
        sqlite_functions(conn)
    row_hash = hash_expression(names)
    key_hash = hash_expression(keys)
    primary = list(table.primary_key.columns)
    if len(primary) == 1 and primary[0].type.python_type is int:
        cast_type = "BIGINT" if dialect != "sqlite" else "INTEGER"
        block = f"CAST({keys[0]} / {BLOCK_SIZE} AS {cast_type})"
    else:
        block = f"substr({key_hash},1,2)" if dialect == "sqlite" else f"substring({key_hash},1,2)"
    if dialect == "sqlite":
        summary = f"SELECT {block} AS block_id,count(*) AS row_count,nexora_block_hash({row_hash}) AS digest FROM {source} GROUP BY {block}"
    elif dialect == "postgresql":
        summary = f"SELECT {block} AS block_id,count(*) AS row_count,md5(string_agg({row_hash},'' ORDER BY {row_hash})) AS digest FROM {source} GROUP BY {block}"
    else:
        summary = f"SELECT block_id,count_big(*) row_count,LOWER(CONVERT(varchar(64),HASHBYTES('SHA2_256',STRING_AGG(CAST(row_hash AS varchar(max)),'') WITHIN GROUP(ORDER BY row_hash)),2)) digest FROM (SELECT {block} block_id,{row_hash} row_hash FROM {source}) src GROUP BY block_id"
    signature = hashlib.sha256(
        json.dumps(
            {
                "version": 1,
                "dialect": dialect,
                "columns": [(c.name, str(c.type), c.nullable) for c in columns],
                "keys": keys,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "columns": columns,
        "source": source,
        "names": names,
        "block": block,
        "summary": summary,
        "signature": signature,
    }
