"""Plotly chart factories for Access-IQ dashboard pages (D-20).

All functions return go.Figure objects. NHS color palette per UI-SPEC.
Standard chart margins: dict(l=40, r=20, t=40, b=40).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# NHS colour palette
NHS_BLUE = "#005EB8"
NHS_LIGHT_BLUE = "#41B6E6"
NHS_PURPLE = "#AE2573"
NHS_DARK_GREEN = "#006747"
NHS_GREEN = "#007F3B"
NHS_RED = "#DA291C"
NHS_YELLOW = "#FFB81C"
NHS_MID_GREY = "#768692"

_MARGINS = dict(l=40, r=20, t=40, b=40)


def grouped_bar(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    y_labels: list[str],
    title: str,
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    """Multi-series grouped bar chart. NHS_BLUE for series 1, NHS_LIGHT_BLUE for series 2."""
    colors = [NHS_BLUE, NHS_LIGHT_BLUE, NHS_PURPLE, NHS_DARK_GREEN]
    fig = go.Figure()
    for i, (y_col, label) in enumerate(zip(y_cols, y_labels, strict=True)):
        fig.add_trace(
            go.Bar(
                x=df[x_col],
                y=df[y_col],
                name=label,
                marker_color=colors[i % len(colors)],
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        barmode="group",
        margin=_MARGINS,
    )
    return fig


def line_trend(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    y_labels: list[str],
    title: str,
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    """Multi-line trend chart. NHS_BLUE for line 1, NHS_LIGHT_BLUE for line 2."""
    colors = [NHS_BLUE, NHS_LIGHT_BLUE, NHS_PURPLE, NHS_DARK_GREEN]
    fig = go.Figure()
    for i, (y_col, label) in enumerate(zip(y_cols, y_labels, strict=True)):
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                name=label,
                mode="lines+markers",
                line=dict(color=colors[i % len(colors)]),
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        margin=_MARGINS,
    )
    return fig


def stacked_bar(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    y_labels: list[str],
    title: str,
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    """Stacked bar chart. NHS_BLUE, NHS_LIGHT_BLUE, NHS_PURPLE for 3 segments."""
    colors = [NHS_BLUE, NHS_LIGHT_BLUE, NHS_PURPLE, NHS_DARK_GREEN]
    fig = go.Figure()
    for i, (y_col, label) in enumerate(zip(y_cols, y_labels, strict=True)):
        fig.add_trace(
            go.Bar(
                x=df[x_col],
                y=df[y_col],
                name=label,
                marker_color=colors[i % len(colors)],
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        barmode="stack",
        margin=_MARGINS,
    )
    return fig


def heatmap_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    z_col: str,
    title: str,
    xaxis_title: str = "",
    yaxis_title: str = "",
    colorscale: list | None = None,
) -> go.Figure:
    """Heatmap chart. Default NHS-themed colorscale."""
    if colorscale is None:
        colorscale = [[0, "#F0F4F5"], [1, NHS_BLUE]]

    # Pivot data for heatmap format
    pivot = df.pivot_table(index=y_col, columns=x_col, values=z_col, aggfunc="sum")
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=[str(r) for r in pivot.index],
            colorscale=colorscale,
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        margin=_MARGINS,
    )
    return fig


def deviation_bar(
    df: pd.DataFrame,
    stratum_col: str,
    deviation_col: str,
    title: str,
    xaxis_title: str = "Deviation from Trust Average (days)",
) -> go.Figure:
    """Horizontal diverging bar. Green for positive, red for negative. Zero baseline."""
    colors = [NHS_GREEN if v >= 0 else NHS_RED for v in df[deviation_col]]
    fig = go.Figure(
        go.Bar(
            x=df[deviation_col],
            y=df[stratum_col],
            orientation="h",
            marker_color=colors,
        )
    )
    fig.add_vline(x=0, line_color=NHS_MID_GREY, line_width=1)
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=stratum_col,
        margin=_MARGINS,
    )
    return fig


def bar_with_suppression(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    """Bar chart with suppressed (NULL y) values shown as yellow hatched zero-height bars."""
    suppressed = df[y_col].isna()
    fig = go.Figure()
    # Normal bars
    fig.add_trace(
        go.Bar(
            x=df.loc[~suppressed, x_col],
            y=df.loc[~suppressed, y_col],
            marker_color=NHS_BLUE,
            name="Value",
        )
    )
    # Suppressed bars -- zero height with hatch
    if suppressed.any():
        fig.add_trace(
            go.Bar(
                x=df.loc[suppressed, x_col],
                y=[0] * suppressed.sum(),
                marker=dict(
                    color=NHS_YELLOW,
                    pattern=dict(shape="/", fgcolor=NHS_YELLOW),
                ),
                customdata=[["Suppressed (< 5 records)"]] * suppressed.sum(),
                hovertemplate="%{customdata[0]}<extra></extra>",
                name="Suppressed",
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        margin=_MARGINS,
    )
    return fig
