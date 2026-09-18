from dash import html

from ..services.datasets import list_extractions


def layout():
    return html.Div(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.Div("DONNÉES / MINIO", className="eyebrow"),
                            html.H1("Extractions"),
                            html.P(
                                "Les collectes publiées restent disponibles après un redémarrage."
                            ),
                        ]
                    )
                ]
            ),
            html.Button("Actualiser", id="refresh-extractions", n_clicks=0, className="nx-button"),
            html.Div(id="extraction-history", className="extraction-history"),
        ]
    )


def history():
    try:
        runs = list_extractions()
    except Exception:  # noqa: BLE001 — avoid exposing connection details
        return html.Div(
            "Stockage indisponible. Vérifiez la connexion MinIO puis actualisez.",
            className="nx-card",
        )
    if not runs:
        return html.Div(
            "Aucune extraction publiée. Lancez une collecte depuis Sources.", className="nx-card"
        )
    return html.Div(
        [
            html.P(f"{len(runs)} dernières extractions"),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th(x)
                                    for x in [
                                        "Source",
                                        "Publication UTC",
                                        "Objets",
                                        "Lignes",
                                        "Portée",
                                        "Emplacement",
                                    ]
                                ]
                            )
                        ),
                        html.Tbody(
                            [
                                html.Tr(
                                    [
                                        html.Td(run["source"]),
                                        html.Td(run["published_at"][:19].replace("T", " ")),
                                        html.Td(run["tables"]),
                                        html.Td(f"{run['rows']:,}".replace(",", " ")),
                                        html.Td("Limitée" if run["truncated"] else "Complète"),
                                        html.Td(run["location"]),
                                    ]
                                )
                                for run in runs
                            ]
                        ),
                    ]
                ),
                className="table-wrap",
            ),
        ],
        className="nx-card",
    )
