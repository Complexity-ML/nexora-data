"""Shared Plotly presentation; no page-specific business calculations."""

from datetime import timedelta

import plotly.graph_objects as go

THEME = go.layout.Template(
    layout={
        "font": {"family": "Inter, Segoe UI, sans-serif", "size": 13, "color": "#52525b"},
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
        "colorway": ["#185c4c", "#4f73c3", "#d59b42"],
        "xaxis": {"showgrid": False, "zeroline": False, "automargin": True},
        "yaxis": {"gridcolor": "#f0f0f2", "zeroline": False, "automargin": True},
        "margin": {"l": 50, "r": 25, "t": 30, "b": 55},
        "legend": {"orientation": "h", "y": 1.13, "x": 0},
    }
)


def usage_chart(result):
    history, forecast = result["history"], result["forecast"]
    fig = go.Figure(layout={"template": THEME, "height": 390, "hovermode": "x unified"})
    fig.add_trace(
        go.Scatter(
            x=[p["date"].isoformat() for p in history],
            y=[p["active_users"] for p in history],
            name="Usage observé",
            mode="lines",
            connectgaps=False,
            line={"width": 2.5},
            hovertemplate="%{y:.0f} utilisateurs<extra></extra>",
        )
    )
    if forecast:
        points = [history[-1], *forecast]
        fig.add_trace(
            go.Scatter(
                x=[p["date"].isoformat() for p in points],
                y=[p["active_users"] for p in points],
                name="Tendance J+7",
                mode="lines+markers",
                line={"dash": "dot", "width": 2.5, "color": "#4f73c3"},
                marker={"size": 5},
                hovertemplate="%{y:.1f} utilisateurs estimés<extra></extra>",
            )
        )
        fig.add_shape(
            type="line",
            x0=history[-1]["date"].isoformat(),
            x1=history[-1]["date"].isoformat(),
            y0=0,
            y1=1,
            yref="paper",
            line={"color": "#a1a1aa", "dash": "dot"},
        )
    if result.get("tree_forecast"):
        points = [history[-1], *result["tree_forecast"]]
        fig.add_trace(
            go.Scatter(
                x=[p["date"].isoformat() for p in points],
                y=[p["active_users"] for p in points],
                name="Arbre J+7",
                mode="lines+markers",
                line={"dash": "dash", "width": 2.5, "color": "#a45a32"},
                marker={"size": 5},
                hovertemplate="%{y:.1f} utilisateurs estimés<extra></extra>",
            )
        )
    for point in history:
        if point["active_users"] is None:
            fig.add_vrect(
                x0=point["date"].isoformat(),
                x1=(point["date"] + timedelta(days=1)).isoformat(),
                fillcolor="#d59b42",
                opacity=0.12,
                line_width=0,
                layer="below",
            )
    fig.update_yaxes(title="Utilisateurs actifs / jour", rangemode="tozero")
    fig.update_xaxes(type="date", tickformat="%d %b")
    return fig
