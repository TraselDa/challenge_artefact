"""Génération de graphiques Plotly depuis les résultats SQL."""

import json
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

# Bleu MATLAB classique — couleur unique pour tous les graphiques
BLUE = "#0072BD"
# Palette pour pie chart uniquement (nécessite des couleurs distinctes)
PIE_COLORS = [
    "#0072BD", "#D95319", "#EDB120", "#7E2F8E",
    "#77AC30", "#4DBEEE", "#A2142F", "#F5A623",
    "#2CA02C", "#9467BD",
]


@dataclass
class ChartConfig:
    """Configuration d'un graphique Plotly."""

    chart_type: str  # "bar", "pie", "histogram", "line"
    x: str  # nom de la colonne X
    y: str  # nom de la colonne Y
    title: str
    x_label: str = ""
    y_label: str = ""


def generate_chart(
    results: list[dict[str, Any]],
    config: ChartConfig,
) -> go.Figure | None:
    """Génère un graphique Plotly depuis les résultats SQL.

    Args:
        results: Liste de dictionnaires (rows SQL).
        config: Configuration du graphique.

    Returns:
        Figure Plotly ou None si impossible de générer.
    """
    if not results:
        logger.warning("Aucun résultat pour générer un graphique")
        return None

    df = pd.DataFrame(results)

    # Vérifier que les colonnes existent
    if config.x not in df.columns:
        logger.warning(f"Colonne X '{config.x}' absente des résultats: {list(df.columns)}")
        return None

    if config.chart_type != "histogram" and config.y not in df.columns:
        logger.warning(f"Colonne Y '{config.y}' absente des résultats: {list(df.columns)}")
        return None

    try:
        fig = _build_figure(df, config)
        fig = _apply_layout(fig, config)
        return fig
    except Exception as e:
        logger.error(f"Erreur génération graphique: {e}")
        return None


def _build_figure(df: pd.DataFrame, config: ChartConfig) -> go.Figure:
    """Construit la figure selon le type."""
    if config.chart_type == "bar":
        fig = px.bar(
            df,
            x=config.x,
            y=config.y,
            title=config.title,
            color_discrete_sequence=[BLUE],
        )
        # Couleur uniforme + fine bordure blanche entre barres
        fig.update_traces(marker_color=BLUE, marker_line_color="white", marker_line_width=0.5)
    elif config.chart_type == "pie":
        fig = px.pie(
            df,
            values=config.y,
            names=config.x,
            title=config.title,
            color_discrete_sequence=PIE_COLORS,
        )
    elif config.chart_type == "histogram":
        fig = px.histogram(
            df,
            x=config.x,
            title=config.title,
            color_discrete_sequence=[BLUE],
        )
        fig.update_traces(marker_color=BLUE, marker_line_color="white", marker_line_width=0.5)
    elif config.chart_type == "line":
        fig = px.line(
            df,
            x=config.x,
            y=config.y,
            title=config.title,
            markers=True,
            color_discrete_sequence=[BLUE],
        )
        fig.update_traces(line_color=BLUE, marker_color=BLUE)
    else:
        # Fallback: bar chart
        logger.warning(f"Type de graphique inconnu '{config.chart_type}', fallback sur 'bar'")
        fig = px.bar(
            df,
            x=config.x,
            y=config.y,
            title=config.title,
            color_discrete_sequence=[BLUE],
        )
        fig.update_traces(marker_color=BLUE, marker_line_color="white", marker_line_width=0.5)

    return fig


def _apply_layout(fig: go.Figure, config: ChartConfig) -> go.Figure:
    """Applique un style MATLAB-like : fond blanc, axes encadrés, grille fine."""
    is_single_color = config.chart_type in ("bar", "histogram", "line")

    TEXT_COLOR = "#222222"

    fig.update_layout(
        template="plotly_white",   # Force fond blanc + texte sombre, écrase le thème Streamlit
        plot_bgcolor="white",
        paper_bgcolor="white",
        font={"family": "Arial, sans-serif", "size": 13, "color": TEXT_COLOR},
        title={
            "text": config.title,
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 16, "color": TEXT_COLOR, "family": "Arial, sans-serif"},
        },
        # Marges généreuses pour que les labels longs ne soient pas coupés
        margin={"l": 80, "r": 40, "t": 70, "b": 100, "autoexpand": True},
        showlegend=not is_single_color,
        legend={
            "bgcolor": "rgba(255,255,255,0.9)",
            "bordercolor": "#AAAAAA",
            "borderwidth": 1,
            "font": {"color": TEXT_COLOR},
        },
    )

    x_label = config.x_label or config.x
    y_label = config.y_label or (config.y if config.chart_type != "histogram" else "Fréquence")

    # Style axes — encadrés comme MATLAB (showline + mirror)
    # Toutes les couleurs de texte explicites pour ne pas hériter du thème Streamlit
    fig.update_xaxes(
        title_text=x_label,
        title_font={"size": 13, "color": TEXT_COLOR},
        tickfont={"color": TEXT_COLOR},
        showgrid=True,
        gridcolor="#DDDDDD",
        gridwidth=1,
        showline=True,
        linecolor="#888888",
        linewidth=1,
        mirror=True,
        ticks="outside",
        ticklen=5,
        tickcolor="#888888",
        automargin=True,
        tickangle=-30 if config.chart_type == "bar" else 0,
    )
    fig.update_yaxes(
        title_text=y_label,
        title_font={"size": 13, "color": TEXT_COLOR},
        tickfont={"color": TEXT_COLOR},
        showgrid=True,
        gridcolor="#DDDDDD",
        gridwidth=1,
        showline=True,
        linecolor="#888888",
        linewidth=1,
        mirror=True,
        ticks="outside",
        ticklen=5,
        tickcolor="#888888",
        automargin=True,
        rangemode="tozero",
    )

    return fig


def chart_to_json(fig: go.Figure) -> str:
    """Sérialise la figure Plotly en JSON.

    Args:
        fig: Figure Plotly.

    Returns:
        JSON string.
    """
    return str(fig.to_json())


def chart_from_json(json_str: str) -> go.Figure:
    """Désérialise un graphique depuis JSON.

    Args:
        json_str: JSON string d'une figure Plotly.

    Returns:
        Figure Plotly reconstruite.
    """
    data = json.loads(json_str)
    return go.Figure(data)
