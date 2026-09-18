"""Paginated UI over the existing usage analysis."""

import csv
import io
from math import ceil
from urllib.parse import urlencode

from dash import Input, Output, State, dash_table, dcc, html
from flask import Response, request, stream_with_context

from ..analytics.opportunities import OpportunityView

KINDS = ["Sans usage observé", "Usage occasionnel", "Usage en baisse"]


def table(ident, columns, selectable=False):
    return dash_table.DataTable(
        id=ident,
        columns=columns,
        data=[],
        page_action="custom",
        page_current=0,
        page_size=25,
        page_count=0,
        row_selectable="single" if selectable else False,
        selected_row_ids=[],
        markdown_options={"link_target": "_self"},
        style_table={"overflowX": "auto"},
        style_cell={
            "textAlign": "left",
            "whiteSpace": "normal",
            "height": "auto",
            "padding": "12px",
            "fontFamily": "inherit",
            "fontSize": "13px",
        },
        style_header={"fontWeight": "600", "backgroundColor": "#f4f5f6"},
    )


def layout(dataset):
    heading = html.Header(
        [
            html.Div("ANALYSE / AIDE À LA REVUE SAM", className="eyebrow"),
            html.H1("Opportunités"),
            html.P(
                "Des usages à examiner pour préparer les réaffectations et les renouvellements."
            ),
        ]
    )
    if dataset is None:
        return html.Div(
            [
                heading,
                html.P(
                    "Aucune collecte analytique disponible. Lancez une collecte complète dans Sources."
                ),
            ]
        )
    return html.Div(
        [
            heading,
            html.P(
                f"28 derniers jours jusqu’au {dataset.end:%d/%m/%Y}. Les baisses comparent deux périodes de 28 jours."
            ),
            html.P(
                "Pistes à valider par le SAM. Une installation signalée n’équivaut pas à une licence récupérable."
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Logiciel", htmlFor="op-search"),
                            dcc.Input(
                                id="op-search",
                                placeholder="Rechercher un logiciel",
                                debounce=True,
                                className="nx-input",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Label("Entité"),
                            dcc.Dropdown(
                                id="op-org",
                                options=[{"label": "Toutes les entités", "value": 0}]
                                + [
                                    {"label": o["name"], "value": o["id"]}
                                    for o in dataset.organizations
                                ],
                                value=0,
                                clearable=False,
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Label("Signal"),
                            dcc.Dropdown(
                                id="op-kind",
                                options=[{"label": "Tous les signaux", "value": ""}]
                                + [{"label": s, "value": s} for s in KINDS],
                                value="",
                                clearable=False,
                            ),
                        ]
                    ),
                ],
                className="op-filters",
            ),
            html.Div(
                [
                    html.P(id="op-count"),
                    html.A("Exporter les résultats filtrés (CSV)", id="op-export"),
                ],
                className="op-toolbar",
            ),
            html.Section(
                table(
                    "op-table",
                    [
                        {
                            "name": label,
                            "id": key,
                            **({"presentation": "markdown"} if key == "analysis" else {}),
                        }
                        for label, key in [
                            ("Logiciel", "software"),
                            ("Entité", "organization"),
                            ("Signal", "kind"),
                            ("Installations", "installations"),
                            ("Observation", "evidence"),
                            ("Couverture", "coverage"),
                            ("Analyse", "analysis"),
                        ]
                    ],
                    True,
                ),
                className="nx-card",
            ),
            html.H2("Installations concernées"),
            html.P(
                "Sélectionnez une ligne pour consulter les installations, 25 par page.",
                id="op-detail-count",
            ),
            html.Section(
                table(
                    "op-details",
                    [
                        {"name": a, "id": b}
                        for a, b in [
                            ("Installation", "id"),
                            ("Machine", "machine_id"),
                            ("Installée le", "installed_on"),
                        ]
                    ],
                ),
                className="nx-card",
            ),
            html.Details(
                [
                    html.Summary("Critères de détection"),
                    html.P(
                        "Sans usage : 0 jour actif. Occasionnel : 1 à 2 jours actifs sur 28. Installation antérieure à la période et couverture complète obligatoires. Baisse : au moins 30 % entre deux périodes de 28 jours entièrement observées, sur les mêmes installations. Les signaux ne s’additionnent pas en licences récupérables."
                    ),
                ]
            ),
        ]
    )


def summary_rows(page):
    rows = []
    for row in page["rows"]:
        row = dict(row)
        query = urlencode(
            {
                "software": row["software_id"],
                "organization": row["organization_id"],
                "start": row["start"],
                "end": row["end"],
            }
        )
        row["id"] = f"{row['software_id']}:{row['organization_id']}:{row['kind']}"
        row["analysis"] = f"[Voir l’analyse](/?{query})"
        row["installations"] = row["count"]
        rows.append(row)
    return rows


def register(app, provider):
    @app.callback(
        Output("op-table", "page_current"),
        Input("op-search", "value"),
        Input("op-org", "value"),
        Input("op-kind", "value"),
    )
    def reset_page(*filters):
        return 0

    @app.callback(Output("op-table", "selected_row_ids"), Input("op-table", "data"))
    def reset_selection(data):
        return []

    @app.callback(
        Output("op-table", "data"),
        Output("op-table", "page_count"),
        Output("op-count", "children"),
        Output("op-export", "href"),
        Input("op-search", "value"),
        Input("op-org", "value"),
        Input("op-kind", "value"),
        Input("op-table", "page_current"),
        State("result", "children"),
    )
    def update(search, org, kind, page, report):
        dataset = provider(report)
        if dataset is None:
            return [], 0, "Collecte supprimée ou indisponible.", None
        view = OpportunityView(dataset)
        result = view.page(search, org, kind, page)
        key = dataset.manifest["storage"]["prefix"] + "/manifest.json"
        href = "/opportunities.csv?" + urlencode(
            {
                "search": search or "",
                "organization": org or 0,
                "kind": kind or "",
                "collection": key,
            }
        )
        return (
            summary_rows(result),
            ceil(result["total"] / 25),
            f"{result['total']} signaux · 25 par page. {view.excluded} installations exclues pour couverture insuffisante.",
            href,
        )

    @app.callback(Output("op-details", "page_current"), Input("op-table", "selected_row_ids"))
    def reset_detail(selection):
        return 0

    @app.callback(
        Output("op-details", "data"),
        Output("op-details", "page_count"),
        Output("op-detail-count", "children"),
        Input("op-table", "selected_row_ids"),
        Input("op-details", "page_current"),
        State("result", "children"),
    )
    def detail(selection, page, report):
        if not selection:
            return [], 0, "Sélectionnez un signal pour consulter ses installations."
        dataset = provider(report)
        if dataset is None:
            return [], 0, "Collecte supprimée ou indisponible."
        try:
            sid, oid, kind = selection[0].split(":", 2)
            scope = (int(sid), int(oid), kind)
        except (ValueError, TypeError):
            return [], 0, "Sélection invalide."
        if kind == KINDS[2]:
            return [], 0, "Signal agrégé de baisse : consultez la courbe dans Analyse."
        result = OpportunityView(dataset).page(page=page, detail=scope)
        return (
            result["rows"],
            ceil(result["total"] / 25),
            f"{result['total']} installations concernées · 25 par page.",
        )

    @app.server.get("/opportunities.csv")
    def export():
        import os
        import re

        from botocore.exceptions import ClientError

        from ..services.datasets import load_dataset
        from ..storage.minio import client_from_env

        key = request.args.get("collection", "")
        if not re.fullmatch(r"bronze/[A-Za-z0-9_-]+/[0-9a-fA-F-]{36}/manifest\.json", key):
            return "Collection invalide", 400
        try:
            org = int(request.args.get("organization", 0))
            dataset = load_dataset(client_from_env(), os.environ["NEXORA_S3_BUCKET"], key)
        except (ValueError, ClientError):
            return "Collection indisponible", 404
        search, kind = request.args.get("search", ""), request.args.get("kind", "")

        def chunks():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            yield "\ufeff"
            for row in OpportunityView(dataset).export_rows(search, org, kind):
                writer.writerow(
                    [
                        "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                        for v in row
                    ]
                )
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

        return Response(
            stream_with_context(chunks()),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=opportunites.csv"},
        )
