"""Metadata discovery only: no SELECT * or COUNT on business tables."""

from datetime import UTC, datetime

from sqlalchemy import inspect

SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "sys", "INFORMATION_SCHEMA"}


def scan(conn, schemas=None):
    inspector = inspect(conn)
    available = inspector.get_schema_names()
    selected = (
        schemas
        if schemas is not None
        else [s for s in available if s not in SYSTEM_SCHEMAS and not s.startswith("pg_toast")]
    )
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("Sélection de schémas vide ou dupliquée.")
    if any(s not in available for s in selected):
        raise ValueError("Un schéma demandé est absent ou inaccessible.")
    objects = []
    for schema in sorted(selected):
        for kind, names in (
            ("table", inspector.get_table_names(schema=schema)),
            ("view", inspector.get_view_names(schema=schema)),
        ):
            for name in sorted(names):
                columns = inspector.get_columns(name, schema=schema)
                obj = {
                    "schema": schema,
                    "name": name,
                    "kind": kind,
                    "columns": [
                        {
                            "name": c["name"],
                            "sql_type": str(c["type"]),
                            "nullable": c.get("nullable"),
                            "default": c.get("default"),
                            "comment": c.get("comment"),
                            "computed": c.get("computed"),
                            "identity": c.get("identity"),
                        }
                        for c in columns
                    ],
                    "unsupported_metadata": [],
                }
                methods = {
                    "primary_key": "get_pk_constraint",
                    "foreign_keys": "get_foreign_keys",
                    "indexes": "get_indexes",
                    "unique_constraints": "get_unique_constraints",
                    "check_constraints": "get_check_constraints",
                    "comment": "get_table_comment",
                }
                for field, method in methods.items():
                    try:
                        obj[field] = getattr(inspector, method)(name, schema=schema)
                    except NotImplementedError:
                        obj[field] = None
                        obj["unsupported_metadata"].append(field)
                objects.append(obj)
    return {
        "catalog_version": 1,
        "scanned_at": datetime.now(UTC).isoformat(),
        "dialect": conn.dialect.name,
        "schemas": selected,
        "objects": objects,
    }
