from datetime import date, timedelta
from urllib.parse import urlencode

from nexora.src.analytics.opportunities import opportunities
from nexora.src.analytics.usage import UsageDataset
from nexora.src.dash_ui.app import create_app
from nexora.src.dash_ui.opportunities import layout


def data():
    start = date(2026, 1, 1)
    tables = {
        "software": [{"id": 1, "name": "Test"}],
        "organizations": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        "machines": [
            {"id": i, "user_id": i, "organization_id": 1 if i < 5 else 2} for i in range(1, 6)
        ],
        "installations": [
            {
                "id": i,
                "machine_id": i,
                "software_id": 1,
                "installed_on": (start + timedelta(days=45 if i == 4 else 0)).isoformat(),
            }
            for i in range(1, 6)
        ],
        "collection_coverage": [
            {
                "organization_id": org,
                "observed_on": (start + timedelta(days=d)).isoformat(),
                "status": "missing" if org == 2 and d == 40 else "complete",
            }
            for org in (1, 2)
            for d in range(56)
        ],
        "usage_observations": [],
    }
    for ident, days in [(2, [30, 32]), (3, list(range(28)) + list(range(28, 35)))]:
        for day in days:
            tables["usage_observations"].append(
                {
                    "installation_id": ident,
                    "observed_on": (start + timedelta(days=day)).isoformat(),
                    "active_minutes": 10,
                }
            )
    return UsageDataset(tables, {})


def test_signals_use_complete_periods_and_eligible_installations():
    dataset = data()
    result = opportunities(dataset)
    rows = {r["kind"]: r for r in result["rows"]}
    assert {i["id"] for i in rows["Sans usage observé"]["installations"]} == {1}
    assert {i["id"] for i in rows["Usage occasionnel"]["installations"]} == {2}
    assert rows["Usage en baisse"]["coverage"] == "56 / 56 jours"
    assert result["excluded"] == 1
    assert all(r["organization_id"] == 1 for r in result["rows"])
    dataset.tables["usage_observations"] *= 2
    assert opportunities(dataset) == result
    dataset.coverage[(1, dataset.end)] = "missing"
    assert opportunities(dataset)["rows"] == []


def test_opportunity_link_selects_same_analysis_scope():
    dataset = data()
    row = opportunities(dataset)["rows"][0]
    rendered = layout(dataset)
    assert "op-table" in str(rendered)
    app = create_app(dataset=dataset)
    client = app.server.test_client()
    try:
        route_key = next(k for k in app.callback_map if k.startswith("..page-dashboard.style"))
        outputs = app.callback_map[route_key]["output"]
        response = client.post(
            "/_dash-update-component",
            json={
                "output": route_key,
                "outputs": [
                    {"id": o.component_id, "property": o.component_property} for o in outputs
                ],
                "inputs": [{"id": "url", "property": "pathname", "value": "/opportunities"}],
                "state": [],
                "changedPropIds": ["url.pathname"],
            },
        )
        assert response.status_code == 200
        assert response.json["response"]["page-opportunities"]["style"] == {}
        key = next(k for k in app.callback_map if k.startswith("..software-filter.value"))
        outputs = app.callback_map[key]["output"]
        query = "?" + urlencode(
            {"software": 1, "organization": 1, "start": row["start"], "end": row["end"]}
        )
        response = client.post(
            "/_dash-update-component",
            json={
                "output": key,
                "outputs": [
                    {"id": o.component_id, "property": o.component_property} for o in outputs
                ],
                "inputs": [
                    {"id": "url", "property": "search", "value": query},
                    {"id": "page-dashboard", "property": "children", "value": None},
                ],
                "state": [{"id": "result", "property": "children", "value": None}],
                "changedPropIds": ["url.search"],
            },
        )
        assert response.status_code == 200
        result = response.json["response"]
        assert result["software-filter"]["value"] == result["organization-filter"]["value"] == 1
        assert result["period-filter"]["start_date"] == row["start"].isoformat()
        assert result["period-filter"]["end_date"] == row["end"].isoformat()
    finally:
        app.explorer.close()


def test_pagination_bounds_filtering_and_detail():
    from nexora.src.analytics.opportunities import OpportunityView

    dataset = data()
    view = OpportunityView(dataset)
    original = view.rows[0]
    view.rows = [
        {**original, "software": f"Logiciel {i:04}", "software_id": i + 1} for i in range(103)
    ]
    first, second = view.page(), view.page(page=1)
    assert first["total"] == 103
    assert len(first["rows"]) == len(second["rows"]) == 25
    assert not {r["software_id"] for r in first["rows"]} & {
        r["software_id"] for r in second["rows"]
    }
    assert all("installations" not in r for r in first["rows"])
    assert len(view.page(page=4)["rows"]) == 3
    assert len(view.page(size=100000)["rows"]) == 100
    assert view.page(search="Logiciel 0001")["total"] == 1
    assert view.page(organization=2)["total"] == 0
    assert len(list(view.export_rows(search="Logiciel 0001"))) == 2
    view.rows[0]["installations"] = [
        {"id": i, "machine_id": i, "installed_on": dataset.start} for i in range(1000)
    ]
    detail = view.page(detail=(1, original["organization_id"], original["kind"]), page=2)
    assert detail["total"] == 1000 and len(detail["rows"]) == 25
    assert detail["rows"][0]["id"] == 50
