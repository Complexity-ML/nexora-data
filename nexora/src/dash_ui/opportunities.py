from urllib.parse import urlencode

from dash import dcc, html

from ..analytics.opportunities import opportunities


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
                html.Div(
                    "Aucune collecte analytique disponible. Lancez une collecte complète dans Sources.",
                    className="nx-card",
                ),
            ]
        )
    result = opportunities(dataset)
    rows = []
    for row in result["rows"]:
        query = urlencode(
            {
                "software": row["software_id"],
                "organization": row["organization_id"],
                "start": row["start"].isoformat(),
                "end": row["end"].isoformat(),
            }
        )
        evidence = [html.P(row["evidence"])]
        if row["installations"]:
            evidence.append(
                html.Details(
                    [
                        html.Summary("Installations concernées"),
                        html.Ul(
                            [
                                html.Li(f"Installation {i['id']} · machine {i['machine_id']}")
                                for i in row["installations"]
                            ]
                        ),
                    ]
                )
            )
        rows.append(
            html.Tr(
                [
                    html.Td(row["software"]),
                    html.Td(row["organization"]),
                    html.Td(row["kind"]),
                    html.Td(str(row["count"]) if row["count"] is not None else "—"),
                    html.Td(evidence),
                    html.Td(row["coverage"]),
                    html.Td(dcc.Link("Voir l’analyse", href="/?" + query)),
                ]
            )
        )
    table = (
        html.Div(
            html.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th(t)
                                for t in [
                                    "Logiciel",
                                    "Entité",
                                    "Signal",
                                    "Installations",
                                    "Observation",
                                    "Couverture",
                                    "Détail",
                                ]
                            ]
                        )
                    ),
                    html.Tbody(rows),
                ]
            ),
            className="table-wrap",
        )
        if rows
        else html.P("Aucun signal répondant aux critères sur cette période.")
    )
    return html.Div(
        [
            heading,
            html.P(
                f"Période du {result['start']:%d/%m/%Y} au {result['end']:%d/%m/%Y}. Les baisses comparent deux périodes de 28 jours."
            ),
            html.P(
                "Pistes à valider par le SAM. Une installation signalée n’équivaut pas à une licence récupérable."
            ),
            html.Section(table, className="nx-card"),
            html.P(
                f"{result['excluded']} installations non évaluées pour absence d’usage ou usage occasionnel : couverture insuffisante."
            ),
            html.Details(
                [
                    html.Summary("Critères de détection"),
                    html.P(
                        "Sans usage : 0 jour actif. Occasionnel : 1 à 2 jours actifs sur 28. Seules les installations présentes avant le début de période et les entités avec 28 jours entièrement observés sont évaluées."
                    ),
                    html.P(
                        "Baisse : au moins 30 % entre deux périodes de 28 jours entièrement observées. Le calcul conserve les installations présentes avant les deux périodes et compte les utilisateurs actifs quotidiens distincts. Un signal invite à examiner le contexte métier."
                    ),
                ]
            ),
        ]
    )
