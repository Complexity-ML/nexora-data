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
assert find(root, "usage-chart") is None, "Les résultats ne doivent pas être préchargés"
assert "Aucun jeu analytique" in json.dumps(root, ensure_ascii=False)
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
    [
        ("url", "pathname", "/extractions"),
        ("refresh-extractions", "n_clicks", 1),
        ('{"key":["ALL"],"type":"delete-extraction"}', "submit_n_clicks", []),
    ],
)
assert "Supprimer" in json.dumps(history, ensure_ascii=False)
print(
    json.dumps(
        {
            "status": "ok",
            "startup_without_results": True,
            "navigation_verified": True,
            "deletion_controls_visible": True,
        }
    )
)
