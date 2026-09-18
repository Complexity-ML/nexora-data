from dash import Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate

from .charts import usage_chart


def metric(label, value, detail):
    return html.Div(
        [
            html.Div(label, className="metric-label"),
            html.Div(value, className="metric-value"),
            html.Div(detail, className="metric-detail"),
        ],
        className="nx-card metric",
    )


def results(dataset, software, organization, start, end):
    result = dataset.analyze(software, organization, start, end)
    forecast = result["forecast"]
    last = result["history"][-1]["date"].strftime("%d/%m/%Y")
    cards = [
        metric(
            "Utilisateurs actifs",
            result["latest"] if result["latest"] is not None else "—",
            f"Observés le {last}",
        ),
        metric(
            "Projection J+7",
            f"{forecast[-1]['active_users']:.1f}" if forecast else "—",
            forecast[-1]["date"].strftime("Estimation au %d/%m/%Y")
            if forecast
            else "Données insuffisantes",
        ),
        metric("Installations", result["installations"], "Dans le périmètre sélectionné"),
        metric(
            "Couverture",
            f"{result['complete_days']} / {len(result['history'])}",
            "Jours entièrement observés",
        ),
    ]
    quality = (
        f"{result['missing_days']} jour(s) de collecte manquante : interruptions dans la courbe, zones ambrées."
        if result["missing_days"]
        else "La collecte couvre tous les jours de la période sélectionnée."
    )
    if not forecast:
        quality += " Projection indisponible : prévoir au moins quatre observations de chaque jour de semaine et une dernière journée complète."
    evaluation = result["evaluation"]
    error = (
        f"Erreur moyenne à J+7 : tendance {evaluation['mae']} · arbre {evaluation['tree_mae']} utilisateurs. "
        f"Comparaison sur les mêmes {evaluation['targets']} dates passées ; plus bas = meilleur."
        if evaluation["mae"] is not None
        else "Historique insuffisant pour mesurer l’erreur à J+7."
    )
    summary = []
    for item in dataset.software:
        analysis = dataset.analyze(item["id"], organization, start, end)
        summary.append(
            html.Tr(
                [
                    html.Td(item["name"]),
                    html.Td(
                        analysis["latest"] if analysis["latest"] is not None else "Non observé"
                    ),
                    html.Td(
                        f"{analysis['forecast'][-1]['active_users']:.1f}"
                        if analysis["forecast"]
                        else "Indisponible"
                    ),
                    html.Td(analysis["installations"]),
                ]
            )
        )
    return cards, usage_chart(result), quality, error, summary


def layout(dataset):
    if dataset is None:
        return html.Div(
            [
                html.H1("Analyse de l’usage"),
                html.Div(
                    "Aucun jeu analytique publié. La collecte SQL reste disponible dans Sources.",
                    className="nx-card",
                ),
            ]
        )
    software = dataset.software[0]["id"]
    start, end = dataset.start.isoformat(), dataset.end.isoformat()
    cards, figure, quality, error, summary = results(dataset, software, 0, start, end)
    return html.Div(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.Div("ANALYSE / USAGE LOGICIEL", className="eyebrow"),
                            html.H1("Usage et projection"),
                            html.P("L’activité observée et son évolution à sept jours."),
                        ]
                    ),
                    html.Span("Données fictives", className="badge"),
                ]
            ),
            html.Div(
                f"Historique de démonstration : {dataset.start:%d/%m/%Y} – {dataset.end:%d/%m/%Y} · Données chargées depuis MinIO.",
                className="dataset-caption",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Logiciel", htmlFor="software-filter"),
                            dcc.Dropdown(
                                id="software-filter",
                                options=[
                                    {"label": s["name"], "value": s["id"]} for s in dataset.software
                                ],
                                value=software,
                                clearable=False,
                                searchable=False,
                                className="nx-select",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Label("Entité", htmlFor="organization-filter"),
                            dcc.Dropdown(
                                id="organization-filter",
                                options=[{"label": "Toutes les entités", "value": 0}]
                                + [
                                    {"label": o["name"], "value": o["id"]}
                                    for o in dataset.organizations
                                ],
                                value=0,
                                clearable=False,
                                searchable=False,
                                className="nx-select",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Label("Période observée"),
                            dcc.DatePickerRange(
                                id="period-filter",
                                start_date=start,
                                end_date=end,
                                min_date_allowed=start,
                                max_date_allowed=end,
                                display_format="DD/MM/YYYY",
                                first_day_of_week=1,
                                minimum_nights=0,
                                clearable=False,
                            ),
                        ],
                        className="period-control",
                    ),
                ],
                className="nx-card dashboard-filters",
            ),
            html.Div(cards, id="usage-metrics", className="metric-grid"),
            html.Section(
                [
                    html.H2("Utilisateurs actifs quotidiens"),
                    dcc.Graph(
                        id="usage-chart",
                        className="usage-chart",
                        style={"height": "420px", "width": "100%", "minWidth": 0},
                        figure=figure,
                        responsive=True,
                        config={"displaylogo": False, "responsive": True},
                    ),
                    html.Div(quality, id="coverage-note", className="quality-note"),
                ],
                className="nx-card chart-card",
            ),
            html.Div(
                [
                    html.Section(
                        [
                            html.H2("Logiciels du périmètre"),
                            html.Div(
                                html.Table(
                                    [
                                        html.Thead(
                                            html.Tr(
                                                [
                                                    html.Th(c)
                                                    for c in [
                                                        "Logiciel",
                                                        "Dernier jour",
                                                        "J+7 estimé",
                                                        "Installations",
                                                    ]
                                                ]
                                            )
                                        ),
                                        html.Tbody(summary, id="software-summary"),
                                    ]
                                ),
                                className="table-wrap",
                            ),
                        ],
                        className="nx-card",
                    ),
                    html.Section(
                        [
                            html.H2("Lire la projection"),
                            html.P(
                                "Les deux courbes comparent la tendance et l’arbre de régression sur les sept jours suivants."
                            ),
                            html.P(error, id="forecast-evaluation"),
                            html.Details(
                                [
                                    html.Summary("Méthode et limites"),
                                    html.P(
                                        "Tendance linéaire séparée pour chaque jour de semaine, sur les huit dernières semaines au maximum. Les jours sans collecte sont exclus. Le calcul utilise uniquement les données antérieures à la date projetée."
                                    ),
                                    html.P(
                                        "Arbre de régression limité à trois niveaux, entraîné sur le même historique avec le jour de semaine et la date. Comparaison à J+7 sans utiliser de données futures. Estimations à population installée constante. Elle ne mesure ni les licences disponibles ni la conformité contractuelle. Une estimation n’est pas une garantie."
                                    ),
                                ]
                            ),
                        ],
                        className="nx-card",
                    ),
                ],
                className="dashboard-bottom",
            ),
            html.Div(id="filter-error", role="status"),
        ]
    )


def dataset_from_report(report):
    import os

    from ..services.datasets import active_key, load_dataset
    from ..storage.minio import client_from_env

    key = report.get("props", {}).get("data-manifest-key") if isinstance(report, dict) else None
    from botocore.exceptions import ClientError

    if not os.environ.get("NEXORA_S3_BUCKET"):
        return None
    client = client_from_env()
    bucket = os.environ["NEXORA_S3_BUCKET"]
    try:
        # The published selection survives page reloads; reading never starts collection.
        key = key or active_key(client, bucket)
        return load_dataset(client, bucket, key) if key else None
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            return None
        raise


def register(app, dataset, provider=None):

    @app.callback(
        Output("usage-metrics", "children"),
        Output("usage-chart", "figure"),
        Output("coverage-note", "children"),
        Output("forecast-evaluation", "children"),
        Output("software-summary", "children"),
        Output("filter-error", "children"),
        Input("software-filter", "value"),
        Input("organization-filter", "value"),
        Input("period-filter", "start_date"),
        Input("period-filter", "end_date"),
        Input("job", "data"),
        Input("url", "pathname"),
        *([State("result", "children")] if dataset is None else []),
    )
    def update(software, organization, start, end, job, path, *reports):
        if software is None or organization is None or not start or not end:
            raise PreventUpdate
        try:
            current = (
                dataset_from_report(reports[0])
                if reports
                else (provider() if provider is not None else dataset)
            )
            if current is None:
                raise PreventUpdate
            return (*results(current, software, organization, start, end), "")
        except ValueError:
            # Clear previous results rather than present them under invalid filters.
            return (
                [],
                {},
                "",
                "",
                [],
                "Sélectionnez une période comprise dans les observations disponibles.",
            )
