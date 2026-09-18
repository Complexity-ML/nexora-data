import argparse
import atexit
import json
import os
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from ..services.explorer import Explorer
from . import dashboard, extractions, opportunities


def metadata_table(obj):
    primary = (obj.get("primary_key") or {}).get("constrained_columns", [])
    foreign = {col for fk in obj.get("foreign_keys") or [] for col in fk["constrained_columns"]}
    return html.Div(
        [
            html.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th(x)
                                for x in ["Champ", "Type SQL", "Nullable", "Clé", "Description"]
                            ]
                        )
                    ),
                    html.Tbody(
                        [
                            html.Tr(
                                [
                                    html.Td(c["name"]),
                                    html.Td(c["sql_type"]),
                                    html.Td("Oui" if c["nullable"] else "Non"),
                                    html.Td(
                                        " · ".join(
                                            x
                                            for x, applies in [
                                                ("PK", c["name"] in primary),
                                                ("FK", c["name"] in foreign),
                                            ]
                                            if applies
                                        )
                                        or "—"
                                    ),
                                    html.Td(c.get("comment") or "—"),
                                ]
                            )
                            for c in obj["columns"]
                        ]
                    ),
                ]
            ),
            html.Details(
                [
                    html.Summary("Relations et métadonnées détaillées"),
                    html.Pre(json.dumps(obj, ensure_ascii=False, indent=2, default=str)),
                ]
            ),
        ],
        className="table-wrap",
    )


def create_app(source_url=None, output=None, demo=False, dataset=None, dataset_provider=None):
    source_url = source_url or os.environ.get("NEXORA_SOURCE_URL")
    explorer = Explorer(source_url, output)
    atexit.register(explorer.close)
    app = Dash(
        __name__,
        title="Nexora · Usage et projection",
        update_title=None,
        assets_folder=str(Path(__file__).parent / "assets"),
        suppress_callback_exceptions=True,
    )
    app.explorer = explorer
    app.layout = html.Div(
        [
            html.Aside(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.Span(), html.Span(), html.Span()],
                                className="logo-mark",
                                **{"aria-hidden": "true"},
                            ),
                            html.Strong("Nexora"),
                        ],
                        className="brand",
                    ),
                    html.Div("DATA WORKSPACE", className="eyebrow"),
                    dcc.Link("Analyse", href="/", id="nav-dashboard", className="nav-active"),
                    dcc.Link(
                        "Opportunités",
                        href="/opportunities",
                        id="nav-opportunities",
                        className="nav-muted",
                    ),
                    dcc.Link("Sources", href="/sources", id="nav-sources", className="nav-muted"),
                    dcc.Link(
                        "Extractions",
                        href="/extractions",
                        id="nav-extractions",
                        className="nav-muted",
                    ),
                    html.Div("Scanner SQL\nExtraction Parquet", className="aside-footer"),
                ]
            ),
            html.Main(
                [
                    html.Header(
                        [
                            html.Div(
                                [
                                    html.Div("SOURCE / EXPLORATION", className="eyebrow"),
                                    html.H1("Explorateur SQL"),
                                    html.P(
                                        "Consultez la structure SQL et collectez les données vers MinIO."
                                    ),
                                ]
                            ),
                            html.Span(
                                "Données fictives"
                                if demo
                                else "Source configurée"
                                if source_url
                                else "Source à configurer",
                                className="badge",
                            ),
                        ]
                    ),
                    html.Div(
                        "Démonstration synthétique · Aucun lien avec le schéma réel de Flexera."
                        if demo
                        else "Accès local · Utiliser un compte SQL en lecture seule. La connexion reste côté serveur.",
                        className="notice",
                    ),
                    html.Section(
                        [
                            html.H2("Collecte SQL"),
                            html.P(
                                "Toutes les tables, vues et colonnes accessibles sont récupérées automatiquement."
                            ),
                            html.Label("Limite de lignes par table (facultatif)", htmlFor="limit"),
                            dcc.Input(
                                id="limit",
                                className="nx-input",
                                type="text",
                                inputMode="numeric",
                                value="",
                                placeholder="Sans limite",
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Scanner la source",
                                        id="scan",
                                        n_clicks=0,
                                        className="nx-button",
                                    ),
                                    html.Button(
                                        "Lancer la collecte",
                                        id="extract",
                                        n_clicks=0,
                                        className="nx-button",
                                    ),
                                ],
                                className="source-actions",
                            ),
                            html.Div(id="catalog-summary", className="summary"),
                        ],
                        className="nx-card collection-controls",
                    ),
                    html.Div("Prêt à explorer.", id="status", role="status", className="status"),
                    html.Section(
                        [
                            html.H2("Structure des champs"),
                            html.Div(
                                "Le catalogue apparaîtra après le scan ou la collecte.",
                                id="metadata",
                            ),
                        ],
                        className="nx-card",
                    ),
                    html.Section(
                        [
                            html.H2("Résultat de l’extraction"),
                            html.Div(
                                "Les résultats et leur provenance apparaîtront ici.", id="result"
                            ),
                        ],
                        className="nx-card",
                    ),
                    dcc.Store(id="catalog"),
                    dcc.Store(id="job"),
                    dcc.Interval(id="poll", interval=800, disabled=True),
                ],
                className="sources-page",
            ),
        ],
        className="shell nx-app",
    )

    sources = app.layout.children[1]
    sources.id = "page-sources"
    sources.style = {"display": "none"}
    # All pages remain mounted so background collection can finish during navigation.
    app.layout.children[1] = html.Main(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="op-mounted-version"),
            html.Div(dashboard.layout(dataset), id="page-dashboard", className="dashboard-page"),
            html.Div(
                sources.children,
                id="page-sources",
                className="sources-page",
                style={"display": "none"},
            ),
            html.Div(
                extractions.layout(),
                id="page-extractions",
                className="extractions-page",
                style={"display": "none"},
            ),
        ]
    )
    app.layout.children[1].children.append(
        html.Div(id="page-opportunities", className="opportunities-page", style={"display": "none"})
    )
    dashboard.register(app, dataset, dataset_provider)
    opportunities.register(
        app,
        lambda report: (
            (dataset_provider() if dataset_provider else dataset)
            if dataset is not None
            else dashboard.dataset_from_report(report)
        ),
    )

    @app.callback(
        Output("page-opportunities", "children"),
        Output("op-mounted-version", "data"),
        Input("url", "pathname"),
        Input("url", "search"),
        Input("result", "children"),
        Input("extraction-history", "children"),
        State("op-mounted-version", "data"),
    )
    def show_opportunities(path, search, report, history, mounted):
        if path != "/opportunities":
            return no_update, no_update
        current = (
            (dataset_provider() if dataset_provider else dataset)
            if dataset is not None
            else dashboard.dataset_from_report(report)
        )
        version = {
            "collection": (
                current.manifest.get("storage", {}).get("prefix", "provided-dataset")
                if current is not None
                else None
            ),
            "scope": list(opportunities.scope(search)),
        }
        if mounted == version:
            return no_update, no_update
        return opportunities.layout(current, search), version

    @app.callback(
        Output("software-filter", "value"),
        Output("organization-filter", "value"),
        Output("period-filter", "start_date"),
        Output("period-filter", "end_date"),
        Input("url", "search"),
        Input("page-dashboard", "children"),
        State("result", "children"),
    )
    def select_opportunity(search, page, report):
        from datetime import date
        from urllib.parse import parse_qs

        if not search:
            return (no_update,) * 4
        try:
            params = parse_qs(search.lstrip("?"))
            sid, oid = int(params["software"][0]), int(params["organization"][0])
            start, end = (
                date.fromisoformat(params["start"][0]),
                date.fromisoformat(params["end"][0]),
            )
            current = dataset if dataset is not None else dashboard.dataset_from_report(report)
            if current is None:
                return (no_update,) * 4
            current.series(sid, oid, start, end)
            return sid, oid, start.isoformat(), end.isoformat()
        except (KeyError, ValueError):
            return (no_update,) * 4

    if dataset is None:

        @app.callback(
            Output("page-dashboard", "children"),
            Input("result", "children"),
            Input("extraction-history", "children"),
        )
        def show_collected_analysis(report, history):
            return dashboard.layout(dashboard.dataset_from_report(report))

    @app.callback(
        Output("page-dashboard", "style"),
        Output("page-sources", "style"),
        Output("page-extractions", "style"),
        Output("page-opportunities", "style"),
        Output("nav-dashboard", "className"),
        Output("nav-sources", "className"),
        Output("nav-extractions", "className"),
        Output("nav-opportunities", "className"),
        Input("url", "pathname"),
    )
    def route(path):
        index = {"/sources": 1, "/extractions": 2, "/opportunities": 3}.get(path, 0)
        return (
            *[{} if i == index else {"display": "none"} for i in range(4)],
            *["nav-active" if i == index else "nav-muted" for i in range(4)],
        )

    @app.callback(
        Output("extraction-history", "children"),
        Input("url", "pathname"),
        Input("refresh-extractions", "n_clicks"),
        Input({"type": "delete-extraction", "key": ALL}, "submit_n_clicks"),
    )
    def extraction_history(path, clicks, deletions):
        triggered = ctx.triggered_id
        if isinstance(triggered, dict) and any(deletions):
            from ..services.datasets import delete_extraction

            try:
                with explorer.lock:
                    if any(not future.done() for _, future in explorer.jobs.values()):
                        raise ValueError("Un traitement est en cours")
                    delete_extraction(triggered["key"])
            except Exception:  # noqa: BLE001 — keep storage credentials out of UI
                return html.Div(
                    [
                        html.P(
                            "Suppression impossible. Vérifiez qu’aucune collecte n’est en cours, puis réessayez.",
                            role="alert",
                        ),
                        extractions.history(),
                    ]
                )
        return extractions.history() if path == "/extractions" else no_update

    @app.callback(
        Output("catalog-summary", "children"),
        Output("metadata", "children"),
        Input("catalog", "data"),
    )
    def show_catalog(catalog):
        if not catalog:
            return "", "Le catalogue apparaîtra après le scan ou la collecte."
        objects = catalog["objects"]
        count = sum(len(obj["columns"]) for obj in objects)
        return f"{len(objects)} objets · {count} champs", [
            html.Details(
                [
                    html.Summary(f"{obj['schema']}.{obj['name']} · {len(obj['columns'])} champs"),
                    metadata_table(obj),
                ]
            )
            for obj in objects
        ]

    @app.callback(Output("poll", "disabled"), Input("job", "data"))
    def poll_only_running_job(job):
        return not bool(job)

    @app.callback(
        Output("catalog", "data"),
        Output("job", "data"),
        Output("status", "children"),
        Output("result", "children"),
        Output("scan", "disabled"),
        Output("extract", "disabled"),
        Input("scan", "n_clicks"),
        Input("extract", "n_clicks"),
        Input("poll", "n_intervals"),
        State("limit", "value"),
        State("job", "data"),
        State("catalog", "data"),
        prevent_initial_call=True,
    )
    def act(scan_clicks, extract_clicks, ticks, limit, job, catalog):
        unchanged = (no_update,) * 6
        if ctx.triggered_id == "poll":
            if not job:
                return unchanged
            result = explorer.poll(job["id"])
            if result is None:
                return unchanged
            if not result["ok"]:
                return no_update, None, result["error"], no_update, False, False
            if "manifest" not in result and "catalog" in result:
                return (
                    result["catalog"],
                    None,
                    "Catalogue disponible. Tous les champs sont inclus dans la collecte.",
                    no_update,
                    False,
                    False,
                )
            manifest = result["manifest"]
            extracted = manifest["objects"]
            report = html.Div(
                [
                    html.Div(
                        f"{sum(obj['rows'] for obj in extracted):,} lignes exportées".replace(
                            ",", " "
                        ),
                        className="result-number",
                    ),
                    html.P(
                        "Extrait tronqué : des lignes supplémentaires existent."
                        if any(obj["truncated"] for obj in extracted)
                        else "Toutes les lignes de la requête ont été exportées."
                    ),
                    html.P(f"{len(extracted)} tables et vues collectées · tous les champs"),
                    html.P(
                        f"{manifest['refresh']['downloaded_rows']:,} lignes récupérées · "
                        f"{manifest['refresh']['reused_blocks']} blocs inchangés réutilisés · "
                        f"{manifest['refresh']['removed_blocks']} blocs retirés".replace(",", " ")
                    )
                    if "refresh" in manifest
                    else None,
                    html.P(
                        "Le dashboard utilise cette collecte."
                        if result.get("analysis_updated")
                        else "Cette extraction ne fournit pas de résultats analytiques complets."
                    ),
                    html.P(f"Stockage : {result['directory']}"),
                ],
                **{
                    "data-manifest-key": (
                        manifest["storage"]["prefix"] + "/manifest.json"
                        if result.get("analysis_updated")
                        else ""
                    )
                },
            )
            return (
                result.get("catalog", no_update),
                None,
                "Extraction terminée · Parquet et manifeste publiés.",
                report,
                False,
                False,
            )
        if job:
            return unchanged
        try:
            if ctx.triggered_id == "scan":
                kind, payload = "scan", None
            else:
                if limit in (None, ""):
                    limit = None
                elif isinstance(limit, str) and limit.strip().isascii() and limit.strip().isdigit():
                    limit = int(limit.strip())
                if limit is not None and (type(limit) is not int or limit < 1):
                    return (
                        no_update,
                        no_update,
                        "La limite doit être un entier positif ou rester vide.",
                        no_update,
                        False,
                        False,
                    )
                kind, payload = (
                    "collect",
                    {
                        "source_label": "demo-enterprise" if demo else "configured-dw",
                        "row_limit": limit,
                    },
                )
            ident = explorer.submit(kind, payload)
            return (
                no_update,
                {"id": ident},
                "Scan en cours…" if kind == "scan" else "Extraction en cours…",
                no_update,
                True,
                True,
            )
        except ValueError:
            return (
                no_update,
                no_update,
                "Un traitement est déjà en cours ou la limite est invalide.",
                no_update,
                False,
                False,
            )

    return app


def main():
    parser = argparse.ArgumentParser(description="Explorateur Nexora local")
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Utiliser data/enterprise.sqlite, sans lire la connexion réelle",
    )
    args = parser.parse_args()
    if args.demo:
        source = "sqlite:///data/enterprise.sqlite"
        if not Path("data/enterprise.sqlite").is_file():
            parser.error("Créer la base fictive avec nexora-demo avant --demo.")
    else:
        source = os.environ.get("NEXORA_SOURCE_URL")
        if not source:
            parser.error("Définir NEXORA_SOURCE_URL ou utiliser --demo.")
    create_app(source, demo=args.demo).run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
