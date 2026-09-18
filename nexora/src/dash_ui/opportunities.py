"""Progressive SAM review: software, scope, then installations."""

import csv
import io
from math import ceil
from urllib.parse import parse_qs, urlencode

from dash import Input, Output, State, ctx, dcc, html
from flask import Response, request, stream_with_context

from ..analytics.opportunities import OpportunityView

KINDS = ["Sans usage observé", "Usage occasionnel", "Usage en baisse"]


def scope(search):
    query = parse_qs((search or "").lstrip("?"))
    try:
        sid = int(query.get("software", ["0"])[0])
        oid = int(query.get("organization", ["0"])[0])
    except ValueError:
        return 0, 0, ""
    kind = query.get("signal", [""])[0]
    return sid, oid, kind if kind in KINDS else ""


def link(label, **params):
    return dcc.Link(
        label,
        href="/opportunities" + ("?" + urlencode(params) if params else ""),
        className="op-link",
    )


def layout(dataset, search=""):
    if dataset is None:
        return html.Div(
            [
                html.H1("Opportunités"),
                html.Div(
                    [
                        html.H2("Aucune analyse disponible"),
                        html.P("Collectez les données du DW pour examiner les usages."),
                        dcc.Link("Ouvrir Sources", href="/sources", className="nx-button"),
                    ],
                    className="op-empty nx-card",
                ),
            ]
        )
    sid, oid, kind = scope(search)
    name = next((s["name"] for s in dataset.software if s["id"] == sid), "")
    organization = next((o["name"] for o in dataset.organizations if o["id"] == oid), "")
    crumbs = [link("Opportunités")]
    if sid:
        crumbs += [html.Span("/"), link(name, software=sid)]
    if oid:
        crumbs += [html.Span("/"), html.Span(organization)]
    title = "Opportunités" if not sid else kind if oid and kind else name
    return html.Div(
        [
            html.Nav(crumbs, className="op-breadcrumb", **{"aria-label": "Fil d’Ariane"}),
            html.Header(
                [
                    html.Div(
                        [
                            html.H1(title),
                            html.P(
                                "Repérez les usages à examiner avant une réaffectation ou un renouvellement."
                            ),
                        ]
                    ),
                    html.A("Exporter en CSV", id="op-export", className="op-export"),
                ],
                className="op-header",
            ),
            html.Div(
                [
                    html.Span("Période observée"),
                    html.Strong(f"28 jours au {dataset.end:%d/%m/%Y}"),
                    html.Span("Collecte complète requise"),
                ],
                className="op-period",
            ),
            html.Div(id="op-summary", className="op-summary"),
            html.Section(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Logiciel", htmlFor="op-search"),
                                    dcc.Input(
                                        id="op-search",
                                        type="search",
                                        disabled=False,
                                        readOnly=False,
                                        placeholder="Rechercher un logiciel…",
                                        debounce=False,
                                        className="nx-input",
                                        value="",
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
                                        value=oid,
                                        clearable=False,
                                        searchable=False,
                                        className="nx-select",
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
                                        value=kind,
                                        clearable=False,
                                        searchable=False,
                                        className="nx-select",
                                    ),
                                ]
                            ),
                        ],
                        className="op-filters",
                        style={"display": "none"} if oid and kind else {},
                    ),
                    html.Div(id="op-table", className="op-table table-wrap"),
                    html.Div(
                        [
                            html.Span(id="op-count"),
                            html.Div(
                                [
                                    html.Button(
                                        "Précédent",
                                        id="op-prev",
                                        n_clicks=0,
                                        className="op-page-button",
                                    ),
                                    html.Span(id="op-page-label"),
                                    html.Button(
                                        "Suivant",
                                        id="op-next",
                                        n_clicks=0,
                                        className="op-page-button",
                                    ),
                                ],
                                className="op-pages",
                            ),
                        ],
                        className="op-pagination",
                    ),
                ],
                className="op-panel",
            ),
            dcc.Store(id="op-page", data=0),
            html.P(
                "Pistes à valider par le SAM. Les volumes affichés représentent des installations, pas des licences récupérables.",
                className="op-footnote",
            ),
            html.Details(
                [
                    html.Summary("Comprendre les critères"),
                    html.P(
                        "Sans usage : aucun jour actif sur 28. Occasionnel : 1 à 2 jours actifs sur 28. Les installations trop récentes et les entités avec une couverture incomplète sont exclues."
                    ),
                    html.P(
                        "Baisse : au moins 30 % entre deux périodes de 28 jours entièrement observées, sur les mêmes installations. Le contexte métier reste à examiner."
                    ),
                ],
                className="op-method",
            ),
        ]
    )


def html_table(headers, rows):
    if not rows:
        return html.Div(
            [
                html.H3("Aucun résultat pour ce périmètre"),
                html.P("Modifiez les filtres ou vérifiez la couverture des observations."),
            ],
            className="op-empty",
        )
    return html.Table(
        [
            html.Thead(html.Tr([html.Th(h) for h in headers])),
            html.Tbody([html.Tr([html.Td(cell) for cell in row]) for row in rows]),
        ]
    )


def render(view, search, org, kind, query, page):
    sid, oid, signal = scope(query)
    filtered = [r for r in view.filtered(search, org, kind) if not sid or r["software_id"] == sid]
    summary = []
    for label in KINDS:
        matching = [r for r in filtered if r["kind"] == label]
        value = (
            sum(r["count"] or 0 for r in matching)
            if label != KINDS[2]
            else len({(r["software_id"], r["organization_id"]) for r in matching})
        )
        unit = "installations" if label != KINDS[2] else "périmètres"
        summary.append(
            html.Div(
                [html.Span(label), html.Strong(f"{value:,}".replace(",", " ")), html.Small(unit)],
                className="op-stat",
            )
        )
    rows = []
    if oid and signal:
        result = view.page(page=page, detail=(sid, oid, signal))
        rows = [
            [str(i["id"]), str(i["machine_id"]), str(i["installed_on"])] for i in result["rows"]
        ]
        headers = ["Installation", "Machine", "Date d’installation"]
        total = result["total"]
        page = result["page"]
        unit = "installations"
    elif sid:
        total = len(filtered)
        page = min(max(0, page), max(0, (total - 1) // 25))
        unit = "signaux"
        headers = ["Entité", "Signal", "Volume", "Observation", "Détail"]
        for r in filtered[page * 25 : (page + 1) * 25]:
            analysis = "/?" + urlencode(
                {
                    "software": sid,
                    "organization": r["organization_id"],
                    "start": r["start"],
                    "end": r["end"],
                }
            )
            action = (
                link(
                    "Voir les installations",
                    software=sid,
                    organization=r["organization_id"],
                    signal=r["kind"],
                )
                if r["count"] is not None
                else dcc.Link("Voir la courbe", href=analysis, className="op-link")
            )
            rows.append(
                [
                    r["organization"],
                    html.Span(r["kind"], className="op-signal"),
                    str(r["count"]) if r["count"] is not None else "—",
                    html.Div([html.P(r["evidence"]), html.Small("Couverture : " + r["coverage"])]),
                    action,
                ]
            )
    else:
        groups = {}
        for r in filtered:
            group = groups.setdefault(
                r["software_id"],
                {"name": r["software"], "zero": 0, "low": 0, "decline": 0, "orgs": set()},
            )
            group["orgs"].add(r["organization_id"])
            if r["kind"] == KINDS[0]:
                group["zero"] += r["count"]
            elif r["kind"] == KINDS[1]:
                group["low"] += r["count"]
            else:
                group["decline"] += 1
        ordered = sorted(
            groups.items(), key=lambda pair: (-pair[1]["zero"], -pair[1]["low"], pair[1]["name"])
        )
        total = len(ordered)
        page = min(max(0, page), max(0, (total - 1) // 25))
        unit = "logiciels"
        headers = [
            "Logiciel",
            "Sans usage",
            "Usage occasionnel",
            "Entités en baisse",
            "Périmètre",
            "",
        ]
        for software, g in ordered[page * 25 : (page + 1) * 25]:
            rows.append(
                [
                    html.Strong(g["name"]),
                    g["zero"],
                    g["low"],
                    g["decline"],
                    f"{len(g['orgs'])} entité(s)",
                    link("Examiner", software=software),
                ]
            )
    pages = max(1, ceil(total / 25))
    count = f"{total} {unit} · {view.excluded} installations exclues pour couverture insuffisante"
    return (
        summary,
        html_table(headers, rows),
        count,
        f"{page + 1} / {pages}",
        page == 0,
        page + 1 >= pages,
    )


def register(app, provider):
    @app.callback(
        Output("op-page", "data"),
        Input("op-prev", "n_clicks"),
        Input("op-next", "n_clicks"),
        Input("op-search", "value"),
        Input("op-org", "value"),
        Input("op-kind", "value"),
        State("op-page", "data"),
    )
    def page(previous, following, search, org, kind, current):
        if ctx.triggered_id == "op-prev":
            return max(0, (current or 0) - 1)
        if ctx.triggered_id == "op-next":
            return (current or 0) + 1
        return 0

    @app.callback(
        Output("op-summary", "children"),
        Output("op-table", "children"),
        Output("op-count", "children"),
        Output("op-page-label", "children"),
        Output("op-prev", "disabled"),
        Output("op-next", "disabled"),
        Output("op-export", "href"),
        Input("op-search", "value"),
        Input("op-org", "value"),
        Input("op-kind", "value"),
        Input("op-page", "data"),
        State("url", "search"),
        State("result", "children"),
    )
    def update(search, org, kind, page, query, report):
        dataset = provider(report)
        if dataset is None:
            return [], html.P("Collecte indisponible."), "", "", True, True, None
        view = OpportunityView(dataset)
        sid, oid, signal = scope(query)
        key = dataset.manifest["storage"]["prefix"] + "/manifest.json"
        href = "/opportunities.csv?" + urlencode(
            {
                "search": search or "",
                "organization": org or 0,
                "kind": kind or "",
                "software": sid,
                "collection": key,
            }
        )
        return (*render(view, search, org, kind, query, page or 0), href)

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
            sid = int(request.args.get("software", 0))
            dataset = load_dataset(client_from_env(), os.environ["NEXORA_S3_BUCKET"], key)
        except (ValueError, ClientError):
            return "Collection indisponible", 404
        view = OpportunityView(dataset)
        if sid:
            view.rows = [r for r in view.rows if r["software_id"] == sid]
        search, kind = request.args.get("search", ""), request.args.get("kind", "")

        def chunks():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            yield "\ufeff"
            for row in view.export_rows(search, org, kind):
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
