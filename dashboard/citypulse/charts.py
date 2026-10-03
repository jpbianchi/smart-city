"""Plotly figure builders. Palette follows the validated reference instance:
blue sequential ramp = bike availability (magnitude), orange sequential ramp =
air-quality burden (second sequential context), neutral chrome ink.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# --- tokens (light surface) -------------------------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SERIES_BLUE = "#2a78d6"

BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
ORANGE_RAMP = ["#fde3d7", "#f8bd9c", "#f29468", "#eb6834", "#c24e1f", "#8f3914"]

FONT = dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK, size=13)


def _ramp_scale(ramp: list[str]) -> list[list]:
    n = len(ramp) - 1
    return [[i / n, c] for i, c in enumerate(ramp)]


def _base_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=FONT,
        showlegend=False,
    )
    return fig


def build_city_map(stations: pd.DataFrame, sensors: pd.DataFrame, center: dict) -> go.Figure:
    fig = go.Figure()

    # zone air-quality layer: one large translucent marker per virtual sensor
    if not sensors.empty:
        fig.add_trace(
            go.Scattermap(
                lat=sensors["lat"], lon=sensors["lon"],
                mode="markers",
                marker=dict(
                    size=46,
                    color=sensors["eaqi"],
                    colorscale=_ramp_scale(ORANGE_RAMP),
                    cmin=0, cmax=100,
                    opacity=0.45,
                ),
                customdata=sensors[["name", "eaqi", "pm2_5", "no2"]],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "European AQI: %{customdata[1]:.0f}<br>"
                    "PM2.5: %{customdata[2]:.1f} µg/m³ · NO₂: %{customdata[3]:.1f} µg/m³"
                    "<extra>air quality</extra>"
                ),
                name="Air quality",
            )
        )

    # station layer: dock telemetry, colored by fill ratio (blue, light→dark)
    st = stations.dropna(subset=["lat", "lon"]).copy()
    st["fill_pct"] = (st["fill_ratio"].fillna(0) * 100).round(0)
    fig.add_trace(
        go.Scattermap(
            lat=st["lat"], lon=st["lon"],
            mode="markers",
            marker=dict(
                size=7,
                color=st["fill_ratio"].fillna(0),
                colorscale=_ramp_scale(BLUE_RAMP),
                cmin=0, cmax=1,
                colorbar=dict(
                    title=dict(text="Fill", font=dict(size=12, color=INK_MUTED)),
                    tickformat=".0%", thickness=10, outlinewidth=0,
                    tickfont=dict(size=11, color=INK_MUTED), len=0.5, y=0.25,
                ),
            ),
            customdata=st[["name", "bikes_available", "docks_available", "capacity", "zone"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]:.0f} bikes · %{customdata[2]:.0f} docks free"
                " · capacity %{customdata[3]:.0f}<br>"
                "zone: %{customdata[4]}"
                "<extra>station</extra>"
            ),
            name="Stations",
        )
    )

    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=center["lat"], lon=center["lon"]), zoom=11.3),
    )
    return _base_layout(fig, 640)


def build_zone_bar(zone_agg: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=zone_agg["bikes"], y=zone_agg["name"],
            orientation="h",
            marker=dict(color=SERIES_BLUE, cornerradius=4),
            customdata=zone_agg[["n_stations", "capacity"]],
            hovertemplate=(
                "<b>%{y}</b><br>%{x:.0f} bikes available<br>"
                "%{customdata[0]} stations · capacity %{customdata[1]:.0f}<extra></extra>"
            ),
        )
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12))
    fig.update_layout(bargap=0.35)
    return _base_layout(fig, 420)


def build_zone_history(zone_hourly: pd.DataFrame, zone_slug: str, zone_name: str) -> go.Figure:
    df = zone_hourly[zone_hourly["zone"] == zone_slug].sort_values("hour")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["hour"], y=df["avg_bikes_available"],
            mode="lines+markers",
            line=dict(color=SERIES_BLUE, width=2),
            marker=dict(size=8),
            hovertemplate="%{x|%H:%M}<br>%{y:.1f} bikes avg<extra></extra>",
            name="Avg bikes per station",
        )
    )
    fig.update_xaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED), rangemode="tozero")
    fig.update_layout(
        title=dict(text=f"Avg bikes per station — {zone_name}", font=dict(size=14)),
        margin=dict(l=8, r=8, t=42, b=8),
    )
    fig = _base_layout(fig, 300)
    fig.update_layout(margin=dict(t=42))
    return fig
