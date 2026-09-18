from dash import dcc, html

from ..services.datasets import list_extractions


def layout():
    return html.Div(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.Div("DONNÉES / MINIO", className="eyebrow"),
                            html.H1("Collectes du DW"),
                            html.P(
                                "Une collecte complète alimente l’analyse. Les autres restent dans l’historique."
                            ),
                        ]
                    )
                ]
            ),
            html.Button("Actualiser", id="refresh-extractions", n_clicks=0, className="nx-button"),
            html.Div(id="extraction-history", className="extraction-history"),
        ]
    )


def delete_button(run):
    return dcc.ConfirmDialogProvider(
        html.Button("Supprimer", className="nx-button nx-delete"),
        id={"type": "delete-extraction", "key": run["manifest_key"]},
        message="Supprimer les fichiers Parquet et le manifeste de cette extraction ? La base SQL est conservée.",
    )


def history_table(runs):
    return html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th(x)
                            for x in [
                                "Publication UTC",
                                "Objets",
                                "Lignes exportées",
                                "État",
                                "Action",
                            ]
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(run["published_at"][:19].replace("T", " ")),
                                html.Td(run["tables"]),
                                html.Td(f"{run['rows']:,}".replace(",", " ")),
                                html.Td(
                                    "Essai limité" if run["truncated"] else "Collecte complète"
                                ),
                                html.Td(delete_button(run)),
                            ]
                        )
                        for run in runs
                    ]
                ),
            ]
        ),
        className="table-wrap",
    )


def history():
    try:
        runs = list_extractions()
    except Exception:  # noqa: BLE001 — do not expose connection details
        return html.Div(
            "Stockage indisponible. Vérifiez la connexion MinIO puis actualisez.",
            className="nx-card",
        )
    current = next((run for run in runs if run["active"]), None)
    archived = [run for run in runs if not run["active"]]
    active = html.Div("Aucune collecte complète utilisée pour l’analyse.", className="nx-card")
    if current:
        active = html.Div(
            [
                html.H2(current["source"]),
                html.Span("Utilisée par le dashboard", className="badge"),
                html.P(
                    f"Collecte complète du {current['published_at'][:19].replace('T', ' ')} UTC"
                ),
                html.P(
                    f"{current['tables']} objets · {current['rows']:,} lignes exportées, vues incluses".replace(
                        ",", " "
                    )
                ),
                html.Details([html.Summary("Emplacement MinIO"), html.Code(current["location"])]),
                delete_button(current),
            ],
            className="nx-card",
        )
    return html.Div(
        [
            active,
            html.Details(
                [
                    html.Summary(f"Historique des collectes ({len(archived)})"),
                    history_table(archived),
                ],
                className="nx-card extraction-archive",
            ),
        ]
    )
