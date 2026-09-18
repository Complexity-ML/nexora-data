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
                    html.Div(
                        [
                            html.Section(
                                [
                                    html.H2("01 · Scanner le catalogue"),
                                    html.P(
                                        "Métadonnées uniquement : aucune ligne métier n’est lue pendant le scan."
                                    ),
                                    html.Label("Schémas à explorer"),
                                    dcc.Input(
                                        id="schemas",
                                        placeholder="Tous les schémas accessibles",
                                        type="text",
                                        debounce=True,
                                    ),
                                    html.Small(
                                        "Plusieurs schémas : séparez leurs noms par une virgule."
                                    ),
                                    html.Button("Scanner la source", id="scan", n_clicks=0),
                                    html.Div(id="catalog-summary", className="summary"),
                                ],
                                className="panel",
                            ),
                            html.Section(
                                [
                                    html.H2("02 · Choisir les données"),
                                    html.Label("Table ou vue"),
                                    dcc.Dropdown(
                                        id="object",
                                        options=[],
                                        placeholder="Lancez d’abord le scan",
                                    ),
                                    html.Label("Champs à extraire"),
                                    dcc.Dropdown(
                                        id="columns",
                                        options=[],
                                        multi=True,
                                        placeholder="Sélection explicite des champs",
                                    ),
                                    html.Label("Limite de lignes"),
                                    dcc.Input(
                                        id="limit",
                                        type="number",
                                        min=1,
                                        max=1000000,
                                        step=1,
                                        value=10000,
                                    ),
                                    html.Small(
                                        "Extrait non ordonné, limité à 1 000 000 lignes dans l’interface."
                                    ),
                                    html.Button(
                                        "Extraire en Parquet →",
                                        id="extract",
                                        n_clicks=0,
                                        disabled=True,
                                    ),
                                ],
                                className="panel",
                            ),
                        ],
                        className="grid",
                    ),
                    html.Div("Prêt à explorer.", id="status", role="status", className="status"),
                    html.Section(
                        [
                            html.H2("Structure des champs"),
                            html.Div(
                                "Sélectionnez une table pour consulter ses métadonnées.",
                                id="metadata",
                            ),
                        ],
                        className="panel",
                    ),
                    html.Section(
                        [
                            html.H2("Résultat de l’extraction"),
                            html.Div(
                                "Les résultats et leur provenance apparaîtront ici.", id="result"
                            ),
                        ],
                        className="panel",
                    ),
                    dcc.Store(id="catalog"),
                    dcc.Store(id="job"),
                    dcc.Interval(id="poll", interval=800),
                ]
            ),
        ],
        className="shell",
    )

    @app.callback(
        Output("object", "options"),
        Output("object", "value"),
        Output("catalog-summary", "children"),
        Input("catalog", "data"),
    )
    def objects(catalog):
        if not catalog:
            return [], None, ""
        objects = catalog["objects"]
        options = [
            {
                "label": f"{o['schema']}.{o['name']} · {o['kind']}",
                "value": json.dumps([o["schema"], o["name"]]),
            }
            for o in objects
        ]
        fields = sum(len(o["columns"]) for o in objects)
        return options, None, f"{len(objects)} objets · {fields} champs · {catalog['dialect']}"

    @app.callback(
        Output("columns", "options"),
        Output("columns", "value"),
        Output("metadata", "children"),
        Input("object", "value"),
        State("catalog", "data"),
    )
    def columns(value, catalog):
        if not value or not catalog:
            return [], [], "Sélectionnez une table pour consulter ses métadonnées."
        schema, name = json.loads(value)
        obj = next(
            (o for o in catalog["objects"] if (o["schema"], o["name"]) == (schema, name)), None
        )
        if not obj:
            return [], [], "Objet introuvable : relancer le scan."
        return (
            [{"label": c["name"], "value": c["name"]} for c in obj["columns"]],
            [],
            metadata_table(obj),
        )

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
        State("schemas", "value"),
        State("object", "value"),
        State("columns", "value"),
        State("limit", "value"),
        State("job", "data"),
        State("catalog", "data"),
        prevent_initial_call=True,
    )
    def act(scan_clicks, extract_clicks, ticks, schemas, value, selected, limit, job, catalog):
        unchanged = (no_update,) * 6
        if ctx.triggered_id == "poll":
            if not job:
                return unchanged
            result = explorer.poll(job["id"])
            if result is None:
                return unchanged
            if not result["ok"]:
                return no_update, None, result["error"], no_update, False, not bool(catalog)
            if "catalog" in result:
                return (
                    result["catalog"],
                    None,
                    "Catalogue disponible. Choisissez une table ou une vue.",
                    no_update,
                    False,
                    False,
                )
            manifest = result["manifest"]
            extracted = manifest["objects"][0]
            report = html.Div(
                [
                    html.Div(
                        f"{extracted['rows']:,} lignes exportées".replace(",", " "),
                        className="result-number",
                    ),
                    html.P(
                        "Extrait tronqué : des lignes supplémentaires existent."
                        if extracted["truncated"]
                        else "Toutes les lignes de la requête ont été exportées."
                    ),
                    html.P(f"Source : {extracted['schema']}.{extracted['name']}"),
                    html.P(f"Stockage : {result['directory']}"),
                    html.P(
                        f"Fichier : {extracted['file']} · Empreinte SHA-256 enregistrée dans manifest.json"
                    ),
                ]
            )
            return (
                no_update,
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
                kind, payload = (
                    "scan",
                    [s.strip() for s in schemas.split(",") if s.strip()] if schemas else None,
                )
            else:
                if not value or not selected or type(limit) is not int or not 1 <= limit <= 1000000:
                    return (
                        no_update,
                        no_update,
                        "Choisissez une table, au moins un champ et une limite entière valide.",
                        no_update,
                        False,
                        not bool(catalog),
                    )
                schema, name = json.loads(value)
                kind, payload = (
                    "extract",
                    {
                        "source_label": "demo-enterprise" if demo else "configured-dw",
                        "objects": [
                            {
                                "schema": schema,
                                "name": name,
                                "columns": selected,
                                "row_limit": limit,
                            }
                        ],
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
                "Un traitement est déjà en cours ou la sélection est invalide.",
                no_update,
                False,
                not bool(catalog),
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
