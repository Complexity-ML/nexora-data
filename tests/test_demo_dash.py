import json
import sqlite3
from threading import Event

import pyarrow.parquet as pq
import pytest

from nexora.src.dash_ui.app import create_app
from nexora.src.demo.generate import generate
from nexora.src.services.explorer import Explorer


@pytest.fixture
def demo(tmp_path):
    path = tmp_path / "enterprise.sqlite"
    generate(path, days=60, users=24)
    return path


def test_demo_integrity_coverage_and_reproducibility(demo, tmp_path):
    other = tmp_path / "same.sqlite"
    generate(other, days=60, users=24)
    with sqlite3.connect(demo) as db, sqlite3.connect(other) as second:
        assert list(db.iterdump()) == list(second.iterdump())
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            db.execute(
                "SELECT COUNT(*) FROM collection_coverage WHERE status='missing'"
            ).fetchone()[0]
            == 3
        )
        assert (
            db.execute("""SELECT COUNT(*) FROM observed_usage u JOIN collection_coverage c
            ON c.organization_id=u.organization_id AND c.observed_on=u.observed_on
            WHERE c.status='missing'""").fetchone()[0]
            == 0
        )
        assert (
            db.execute("""SELECT COUNT(*) FROM usage_observations u JOIN installations i
            ON i.id=u.installation_id WHERE u.observed_on<i.installed_on""").fetchone()[0]
            == 0
        )
    original = demo.read_bytes()
    with pytest.raises(FileExistsError):
        generate(demo)
    assert demo.read_bytes() == original


def callback(client, app, prefix, trigger, inputs, states=()):
    key = next(k for k in app.callback_map if k.startswith(prefix))
    outputs = app.callback_map[key]["output"]
    response = client.post(
        "/_dash-update-component",
        json={
            "output": key,
            "outputs": [{"id": o.component_id, "property": o.component_property} for o in outputs],
            "changedPropIds": [trigger],
            "inputs": [
                {"id": ident, "property": prop, "value": value} for ident, prop, value in inputs
            ],
            "state": [
                {"id": ident, "property": prop, "value": value} for ident, prop, value in states
            ],
        },
    )
    assert response.status_code == 200, response.data
    return response.json["response"]


def test_dash_http_scan_select_extract(demo, tmp_path):
    app = create_app(f"sqlite:///{demo}", tmp_path / "bronze", demo=True)
    client = app.server.test_client()
    try:
        assert client.get("/").status_code == 200
        layout = client.get("/_dash-layout")
        assert layout.status_code == 200
        assert str(demo) not in layout.text
        assert client.get("/assets/style.css").status_code == 200
        inputs = [("scan", "n_clicks", 1), ("extract", "n_clicks", 0), ("poll", "n_intervals", 0)]
        states = [
            ("schemas", "value", "main"),
            ("object", "value", None),
            ("columns", "value", []),
            ("limit", "value", 100),
            ("job", "data", None),
            ("catalog", "data", None),
        ]
        started = callback(client, app, "..catalog.data", "scan.n_clicks", inputs, states)
        job = started["job"]["data"]
        app.explorer.jobs[job["id"]][1].result(timeout=10)
        states[4] = ("job", "data", job)
        finished = callback(client, app, "..catalog.data", "poll.n_intervals", inputs, states)
        catalog = finished["catalog"]["data"]
        assert len(catalog["objects"]) == 9
        choices = callback(
            client, app, "..object.options", "catalog.data", [("catalog", "data", catalog)]
        )
        assert len(choices["object"]["options"]) == 9
        value = json.dumps(["main", "usage_observations"])
        fields = callback(
            client,
            app,
            "..columns.options",
            "object.value",
            [("object", "value", value)],
            [("catalog", "data", catalog)],
        )
        assert {o["value"] for o in fields["columns"]["options"]} == {
            "id",
            "installation_id",
            "observed_on",
            "active_minutes",
        }
        states[1] = ("object", "value", value)
        states[2] = ("columns", "value", ["id", "active_minutes"])
        states[4] = ("job", "data", None)
        states[5] = ("catalog", "data", catalog)
        started = callback(client, app, "..catalog.data", "extract.n_clicks", inputs, states)
        job = started["job"]["data"]
        result = app.explorer.jobs[job["id"]][1].result(timeout=10)
        assert result["ok"]
        assert result["manifest"]["objects"][0]["truncated"]
        states[4] = ("job", "data", job)
        finished = callback(client, app, "..catalog.data", "poll.n_intervals", inputs, states)
        assert "terminée" in finished["status"]["children"]
        parquet = next((tmp_path / "bronze").glob("*/*.parquet"))
        table = pq.read_table(parquet)
        assert table.column_names == ["id", "active_minutes"]
        assert table.num_rows == 100
        states[4] = ("job", "data", None)
        states[2] = ("columns", "value", [])
        invalid = callback(client, app, "..catalog.data", "extract.n_clicks", inputs, states)
        assert "au moins un champ" in invalid["status"]["children"]
    finally:
        app.explorer.close()


def test_worker_rejects_parallel_jobs(demo, tmp_path, monkeypatch):
    explorer = Explorer(f"sqlite:///{demo}", tmp_path / "bronze")
    release = Event()
    monkeypatch.setattr(explorer, "_run", lambda *args: release.wait(timeout=5))
    try:
        explorer.submit("scan", None)
        with pytest.raises(ValueError, match="en cours"):
            explorer.submit("scan", None)
    finally:
        release.set()
        explorer.close()


def test_worker_hides_sensitive_driver_errors(tmp_path):
    explorer = Explorer("postgresql+missing://secret:password@private-host/db", tmp_path)
    try:
        job = explorer.submit("scan", None)
        explorer.jobs[job][1].result(timeout=10)
        result = explorer.poll(job)
        assert not result["ok"]
        assert not any(s in json.dumps(result) for s in ["password", "private-host", "secret"])
    finally:
        explorer.close()
