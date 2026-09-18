"""Run inside the app container: verify actual Dash HTTP callbacks and MinIO readback."""

import hashlib
import io
import json
import time
from pathlib import Path

import pyarrow.parquet as pq
import requests

from nexora.src.storage.minio import client_from_env

base = "http://127.0.0.1:8051"
session = requests.Session()
response = session.get(base + "/_dash-layout", timeout=10)
response.raise_for_status()
assert "Scanner la source" in response.text

deps = session.get(base + "/_dash-dependencies", timeout=10).json()
key = next(dep["output"] for dep in deps if dep["output"].startswith("..catalog.data"))
outputs = [
    {"id": i, "property": p}
    for i, p in [
        ("catalog", "data"),
        ("job", "data"),
        ("status", "children"),
        ("result", "children"),
        ("scan", "disabled"),
        ("extract", "disabled"),
    ]
]
inputs = [
    {"id": i, "property": p, "value": v}
    for i, p, v in [("scan", "n_clicks", 1), ("extract", "n_clicks", 0), ("poll", "n_intervals", 0)]
]
state = [
    {"id": "limit", "property": "value", "value": 100},
    {"id": "job", "property": "data", "value": None},
    {"id": "catalog", "property": "data", "value": None},
]


def call(trigger):
    result = session.post(
        base + "/_dash-update-component",
        json={
            "output": key,
            "outputs": outputs,
            "changedPropIds": [trigger],
            "inputs": inputs,
            "state": state,
        },
        timeout=15,
    )
    if result.status_code == 204:
        return {}
    result.raise_for_status()
    return result.json()["response"]


def wait_job():
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = call("poll.n_intervals")
        if "job" in result and result["job"]["data"] is None:
            assert "Échec" not in result["status"]["children"], result["status"]
            return result
        time.sleep(0.2)
    raise TimeoutError("Traitement non terminé")


started = call("scan.n_clicks")
state[1]["value"] = started["job"]["data"]
catalog = wait_job()["catalog"]["data"]
assert len(catalog["objects"]) == 9
state[1]["value"] = None
state[2]["value"] = catalog
inputs[1]["value"] = 1
started = call("extract.n_clicks")
state[1]["value"] = started["job"]["data"]
result = wait_job()
report = result["result"]["children"]["props"]["children"]
location = next(
    c["props"]["children"]
    for c in report
    if isinstance(c["props"].get("children"), str)
    and c["props"]["children"].startswith("Stockage : s3://")
)
uri = location.removeprefix("Stockage : s3://")
bucket, prefix = uri.split("/", 1)
client = client_from_env()
manifest = json.loads(
    client.get_object(Bucket=bucket, Key=prefix + "/manifest.json")["Body"].read()
)
assert len(manifest["objects"]) == 9
obj = next(o for o in manifest["objects"] if o["name"] == "usage_observations")
content = client.get_object(Bucket=bucket, Key=obj["key"])["Body"].read()
assert hashlib.sha256(content).hexdigest() == obj["sha256"]
table = pq.read_table(io.BytesIO(content))
assert table.num_rows == 100
assert table.column_names == ["id", "installation_id", "observed_on", "active_minutes"]
assert obj["truncated"]
assert not list(Path("/app/data").glob("**/*.parquet"))
print(
    json.dumps(
        {
            "status": "ok",
            "catalog_objects": 9,
            "parquet_rows": table.num_rows,
            "storage": "s3://" + uri,
            "sha256_verified": True,
        }
    )
)
