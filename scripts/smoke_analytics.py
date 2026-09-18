"""Verify the live analytics UI through HTTP only, with no browser automation."""

import json

import requests

base = "http://127.0.0.1:8051"
session = requests.Session()
layout = session.get(base + "/_dash-layout", timeout=15)
layout.raise_for_status()


def find(node, ident):
    if isinstance(node, dict):
        if node.get("props", {}).get("id") == ident:
            return node["props"]
        for value in node.values():
            result = find(value, ident)
            if result is not None:
                return result
    if isinstance(node, list):
        for value in node:
            result = find(value, ident)
            if result is not None:
                return result
    return None


root = layout.json()
chart = find(root, "usage-chart")["figure"]
assert len(chart["data"][0]["x"]) == 90
assert len(chart["data"][1]["x"]) == 8
assert any(value is None for value in chart["data"][0]["y"])
assert len(find(root, "usage-metrics")["children"]) == 4
assert find(root, "limit")["type"] == "text"
assert find(root, "nav-dashboard")["href"] == "/"
assert find(root, "nav-sources")["href"] == "/sources"
assert find(root, "nav-extractions")["href"] == "/extractions"
assert find(root, "page-sources")["style"] == {"display": "none"}
deps = session.get(base + "/_dash-dependencies", timeout=10).json()


def callback(prefix, values):
    key = next(dep["output"] for dep in deps if dep["output"].startswith(prefix))
    properties = key.strip(".").split("...") if key.startswith("..") else [key]
    outputs = [{"id": p.rsplit(".", 1)[0], "property": p.rsplit(".", 1)[1]} for p in properties]
    data = {
        "output": key,
        "outputs": outputs if key.startswith("..") else outputs[0],
        "inputs": [{"id": i, "property": p, "value": v} for i, p, v in values],
        "state": [],
        "changedPropIds": [values[0][0] + "." + values[0][1]],
    }
    response = session.post(base + "/_dash-update-component", json=data, timeout=15)
    response.raise_for_status()
    return response.json()["response"]


source = callback("..page-dashboard", [("url", "pathname", "/sources")])
assert source["page-sources"]["style"] == {}
assert source["page-dashboard"]["style"] == {"display": "none"}
history = callback(
    "extraction-history",
    [("url", "pathname", "/extractions"), ("refresh-extractions", "n_clicks", 1)],
)
assert "demo-analytics" in json.dumps(history)
assert "s3://" in json.dumps(history)
period = find(root, "period-filter")
filtered = callback(
    "..usage-metrics",
    [
        ("software-filter", "value", 2),
        ("organization-filter", "value", 1),
        ("period-filter", "start_date", period["start_date"]),
        ("period-filter", "end_date", period["end_date"]),
    ],
)
assert filtered["usage-chart"]["figure"]["data"][0]["y"] != chart["data"][0]["y"]
assert len(filtered["usage-chart"]["figure"]["data"][1]["x"]) == 8
assert "tous les jours" in filtered["coverage-note"]["children"]
print(
    json.dumps(
        {
            "status": "ok",
            "historical_days": 90,
            "forecast_days": 7,
            "dashboard_populated": True,
            "navigation_verified": True,
            "filters_verified": True,
            "persisted_extractions_visible": True,
        }
    )
)
