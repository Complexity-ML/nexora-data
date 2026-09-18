import copy
import json
import sqlite3
from datetime import date, timedelta

import boto3
import pytest
from moto import mock_aws

from nexora.src.analytics.usage import UsageDataset
from nexora.src.dash_ui.app import create_app
from nexora.src.demo.generate import generate
from nexora.src.forecasting.statistical import backtest, predict
from nexora.src.services.datasets import TABLES, ensure_demo, list_extractions


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "demo.sqlite"
    generate(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            name: [dict(row) for row in conn.execute(f'SELECT * FROM "{name}"')] for name in TABLES
        }
    return UsageDataset(tables, {"run_id": "fixture"})


def test_missing_coverage_is_not_zero_and_filters_are_exact(dataset):
    complete = dataset.analyze(1, 0, dataset.start, dataset.end)
    assert len(complete["history"]) == 90
    assert complete["missing_days"] == 3
    assert len(complete["forecast"]) == 7
    org_a = dataset.analyze(1, 1, dataset.start, dataset.end)
    org_b = dataset.analyze(1, 2, dataset.start, dataset.end)
    assert org_a["missing_days"] == 0
    assert org_b["missing_days"] == 3
    assert org_a["installations"] < complete["installations"]
    day = dataset.end
    expected = {
        dataset.machines[dataset.installations[o["installation_id"]]["machine_id"]]["user_id"]
        for o in dataset.tables["usage_observations"]
        if o["observed_on"] == day.isoformat()
        and dataset.installations[o["installation_id"]]["software_id"] == 1
    }
    assert complete["latest"] == len(expected)
    assert complete["evaluation"]["targets"] == 14
    assert complete["forecast"][-1]["date"] == dataset.end + timedelta(days=7)
    assert all(0 <= p["active_users"] <= complete["population"] for p in complete["forecast"])


def test_known_weekday_trend_and_short_history():
    start = date(2026, 1, 5)
    history = [
        {"date": start + timedelta(days=i), "active_users": 30 + i + (i % 7) * 3} for i in range(70)
    ]
    forecast = predict(history)
    assert forecast[-1]["active_users"] == 30 + 76 + (76 % 7) * 3
    assert backtest(history)["mae"] == 0
    assert predict(history[:14]) == []
    history[-1]["active_users"] = None
    assert predict(history) == []


def test_history_cutoff_and_deduplication(dataset):
    cutoff = dataset.end - timedelta(days=14)
    before = dataset.analyze(2, 0, dataset.start, cutoff)
    altered = copy.deepcopy(dataset.tables)
    altered["usage_observations"] = [
        o for o in altered["usage_observations"] if date.fromisoformat(o["observed_on"]) <= cutoff
    ]
    altered["usage_observations"] *= 2
    after = UsageDataset(altered, {}).analyze(2, 0, dataset.start, cutoff)
    assert before == after
    short = dataset.analyze(1, 0, dataset.end - timedelta(days=6), dataset.end)
    assert short["forecast"] == []
    with pytest.raises(ValueError):
        dataset.analyze(1, 0, dataset.start - timedelta(days=1), dataset.end)


def test_full_demo_persists_and_reuses_same_manifest(tmp_path):
    path = tmp_path / "demo.sqlite"
    generate(path)
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        client.create_bucket(Bucket="nexora-demo")
        first = ensure_demo(f"sqlite:///{path}", client=client, bucket="nexora-demo")
        second = ensure_demo("sqlite:///does-not-exist", client=client, bucket="nexora-demo")
        assert first.manifest["run_id"] == second.manifest["run_id"]
        assert len(list_extractions(client, bucket="nexora-demo")) == 1
        assert len(second.tables["usage_observations"]) == 17351


def test_dashboard_http_has_results_and_functional_filters(dataset):
    app = create_app("sqlite:///unused", demo=True, dataset=dataset)
    client = app.server.test_client()
    try:
        layout = client.get("/_dash-layout").json
        text = json.dumps(layout)
        assert '"id": "usage-chart"' in text
        assert "Projection J+7" in text
        assert "usage-metrics" in text
        key = next(k for k in app.callback_map if k.startswith("..usage-metrics"))

        def call(software, organization, start, end):
            outputs = app.callback_map[key]["output"]
            r = client.post(
                "/_dash-update-component",
                json={
                    "output": key,
                    "outputs": [
                        {"id": o.component_id, "property": o.component_property} for o in outputs
                    ],
                    "inputs": [
                        {"id": i, "property": p, "value": v}
                        for i, p, v in [
                            ("software-filter", "value", software),
                            ("organization-filter", "value", organization),
                            ("period-filter", "start_date", start),
                            ("period-filter", "end_date", end),
                            ("job", "data", None),
                            ("url", "pathname", "/"),
                        ]
                    ],
                    "state": [],
                    "changedPropIds": ["software-filter.value"],
                },
            )
            assert r.status_code == 200, r.data
            return r.json["response"]

        full = call(1, 0, dataset.start.isoformat(), dataset.end.isoformat())
        entity = call(2, 1, dataset.start.isoformat(), dataset.end.isoformat())
        assert len(full["usage-chart"]["figure"]["data"][0]["x"]) == 90
        assert len(full["usage-chart"]["figure"]["data"][1]["x"]) == 8
        assert (
            full["usage-chart"]["figure"]["data"][0]["y"]
            != entity["usage-chart"]["figure"]["data"][0]["y"]
        )
        short = call(1, 0, (dataset.end - timedelta(days=6)).isoformat(), dataset.end.isoformat())
        assert len(short["usage-chart"]["figure"]["data"]) == 1
        assert "indisponible" in short["coverage-note"]["children"]
        bad = call(1, 0, "2020-01-01", dataset.end.isoformat())
        assert bad["usage-chart"]["figure"] == {}
    finally:
        app.explorer.close()


def test_observed_inactivity_is_zero_not_missing(dataset):
    tables = copy.deepcopy(dataset.tables)
    tables["usage_observations"] = []
    empty = UsageDataset(tables, {}).analyze(1, 1, dataset.start, dataset.end)
    assert empty["missing_days"] == 0
    assert all(point["active_users"] == 0 for point in empty["history"])
    assert all(point["active_users"] == 0 for point in empty["forecast"])


def test_dashboard_uses_new_full_dw_collection_but_not_limited_trials(tmp_path, monkeypatch):
    from nexora.src.services.datasets import DatasetReader
    from nexora.src.services.explorer import Explorer

    path = tmp_path / "dw.sqlite"
    generate(path)
    url = f"sqlite:///{path}"
    for key, value in {
        "NEXORA_S3_ENDPOINT": "https://s3.amazonaws.com",
        "NEXORA_S3_ACCESS_KEY": "testing",
        "NEXORA_S3_SECRET_KEY": "testing",
        "NEXORA_S3_BUCKET": "nexora-demo",
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        client.create_bucket(Bucket="nexora-demo")
        initial = ensure_demo(url, client=client, bucket="nexora-demo")
        reader = DatasetReader(initial)
        assert initial.manifest["source_label"] == "demo-enterprise"
        assert len(initial.manifest["objects"]) == 9
        assert initial.analyze(1, 0, initial.start, initial.end)["latest"] > 0
        with sqlite3.connect(path) as conn:
            conn.execute(
                "DELETE FROM usage_observations WHERE observed_on=?", (initial.end.isoformat(),)
            )
        explorer = Explorer(url)
        try:
            job = explorer.submit("collect", {"source_label": "demo-enterprise", "row_limit": None})
            full = explorer.jobs[job][1].result(timeout=15)
            assert full["ok"] and full["analysis_updated"]
            updated = reader.get()
            assert updated.manifest["run_id"] != initial.manifest["run_id"]
            assert updated.analyze(1, 0, updated.start, updated.end)["latest"] == 0
            job = explorer.submit("collect", {"source_label": "demo-enterprise", "row_limit": 1})
            limited = explorer.jobs[job][1].result(timeout=15)
            assert limited["ok"] and not limited["analysis_updated"]
            assert reader.get().manifest["run_id"] == updated.manifest["run_id"]
            runs = list_extractions(client, bucket="nexora-demo")
            assert sum(run["active"] for run in runs) == 1
            assert {run["source"] for run in runs} == {"demo-enterprise"}
        finally:
            explorer.close()


def test_tree_calendar_forecast_and_paired_backtest():
    start = date(2026, 1, 5)
    history = [
        {"date": start + timedelta(days=i), "active_users": 60 if i % 7 < 5 else 10}
        for i in range(90)
    ]
    forecast = predict(history, tree=True)
    assert len(forecast) == 7
    assert [p["active_users"] for p in forecast] == [
        60 if p["date"].weekday() < 5 else 10 for p in forecast
    ]
    score = backtest(history)
    assert score["targets"] == 14
    assert score["mae"] == score["tree_mae"] == 0
    assert all(p["active_users"] <= 20 for p in predict(history, population=20, tree=True))
    assert predict(history[:20], tree=True) == []
    history[-1]["active_users"] = None
    assert predict(history, tree=True) == []
