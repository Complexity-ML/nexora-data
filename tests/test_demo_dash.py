import json
import sqlite3
from pathlib import Path
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


def test_dash_http_collect_all(demo, tmp_path):
    app = create_app(f"sqlite:///{demo}", tmp_path / "bronze", demo=True)
    client = app.server.test_client()
    try:
        assert client.get("/").status_code == 200
        layout = client.get("/_dash-layout")
        assert layout.status_code == 200
        assert str(demo) not in layout.text
        for stylesheet in ("theme", "layout", "components", "sources"):
            assert client.get(f"/assets/{stylesheet}.css").status_code == 200
        inputs = [("scan", "n_clicks", 0), ("extract", "n_clicks", 1), ("poll", "n_intervals", 0)]
        states = [("limit", "value", 100), ("job", "data", None), ("catalog", "data", None)]
        started = callback(client, app, "..catalog.data", "extract.n_clicks", inputs, states)
        job = started["job"]["data"]
        result = app.explorer.jobs[job["id"]][1].result(timeout=10)
        assert result["ok"], result
        states[1] = ("job", "data", job)
        finished = callback(client, app, "..catalog.data", "poll.n_intervals", inputs, states)
        assert "terminée" in finished["status"]["children"]
        assert len(finished["catalog"]["data"]["objects"]) == 9
        manifest = result["manifest"]
        assert len(manifest["objects"]) == 9
        obj = next(o for o in manifest["objects"] if o["name"] == "usage_observations")
        assert obj["truncated"]
        table = pq.read_table(Path(result["directory"]) / obj["file"])
        assert table.column_names == ["id", "installation_id", "observed_on", "active_minutes"]
        assert table.num_rows == 100
        # An empty limit really exports the full source, including every view/column.
        job = app.explorer.submit("collect", {"source_label": "full-test", "row_limit": None})
        complete = app.explorer.jobs[job][1].result(timeout=10)
        assert complete["ok"], complete
        assert all(not o["truncated"] for o in complete["manifest"]["objects"])
        assert (
            next(
                o["rows"]
                for o in complete["manifest"]["objects"]
                if o["name"] == "usage_observations"
            )
            > 100
        )
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
