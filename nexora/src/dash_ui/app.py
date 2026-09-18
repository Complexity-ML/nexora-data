import argparse
import atexit
import json
import os
from pathlib import Path

from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

from ..services.explorer import Explorer


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


def create_app(source_url=None, output=None, demo=False):
    source_url = source_url or os.environ.get("NEXORA_SOURCE_URL")
    explorer = Explorer(source_url, output)
    atexit.register(explorer.close)
    app = Dash(
        __name__,
        title="Nexora · Explorateur SQL",
        assets_folder=str(Path(__file__).parent / "assets"),
    )
    app.explorer = explorer
    app.layout = html.Div(
        [
            html.Aside(
                [
                    html.Div("nexora", className="brand"),
                    html.Div("DATA WORKSPACE", className="eyebrow"),
                    html.Div("01  Explorer la source", className="nav-active"),
                    html.Div("02  Bronze Parquet", className="nav-muted"),
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
                                        "Explorez la structure SQL, choisissez vos champs et préparez votre Bronze."
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
                                type="number",
                                min=1,
                                step=1,
                                value=None,
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
                    dcc.Interval(id="poll", interval=800),
                ],
                className="sources-page",
            ),
        ],
        className="shell nx-app",
    )

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
                    html.P(f"Stockage : {result['directory']}"),
                ]
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
