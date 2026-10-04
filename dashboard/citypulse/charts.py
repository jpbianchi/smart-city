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


GAP_DIVERGING = [
    [0.0, "#b3261e"], [0.25, "#e66767"], [0.5, "#a9a8a2"], [0.75, "#5598e7"], [1.0, "#184f95"],
]


def build_property_map(df: pd.DataFrame, center: dict, selected_id: str | None = None) -> go.Figure:
    """One marker per property, diverging color on the value gap BEYOND the
    model's error band: gaps inside the band are noise and stay gray;
    blue = priced below fair value, red = above."""
    band = float(df["model_median_ape_pct"].iloc[0]) if not df.empty else 15.0
    gap = df["value_gap_pct"]
    signal = gap.clip(lower=0).sub(band).clip(lower=0) - (-gap).clip(lower=0).sub(band).clip(lower=0)
    # pre-formatted hover text: mixed-type customdata disables plotly number formats.
    # Built row-wise: vectorized str + Series.map() breaks on an empty selection
    # (pandas 3 returns float64 for map() over zero rows).
    hover = [
        f"<b>{r.address}</b> · {r.arrondissement}<br>{r.surface_m2:.0f} m² · asking "
        f"{r.asking_eur:,.0f} €<br>fair value {r.fair_value_eur:,.0f} € ({r.value_gap_pct:+.0f}%)"
        f"<br>opportunity {r.opportunity_grade} · {r.opportunity_score:.0f}/100 — click for the dossier"
        .replace(",", " ")
        for r in df.itertuples()
    ]
    fig = go.Figure()
    fig.add_trace(
        go.Scattermap(
            lat=df["lat"], lon=df["lon"],
            mode="markers",
            marker=dict(
                size=10,
                color=signal.clip(-20, 20),
                colorscale=GAP_DIVERGING, cmin=-20, cmax=20,
                colorbar=dict(
                    title=dict(text=f"Gap beyond<br>±{band:.0f}% error", font=dict(size=11, color=INK_MUTED)),
                    thickness=10, outlinewidth=0,
                    tickvals=[-20, -10, 0, 10, 20],
                    ticktext=["overpriced", "", "fair", "", "underpriced"],
                    tickfont=dict(size=10, color=INK_MUTED), len=0.6, y=0.3,
                ),
            ),
            text=hover,
            hovertemplate="%{text}<extra></extra>",
            hoverlabel=dict(bgcolor="#fcfcfb", bordercolor="#c3c2b7", font=dict(color=INK, size=12)),
            name="Properties",
        )
    )
    if selected_id is not None:
        sel = df[df["tx_id"] == selected_id]
        if not sel.empty:
            fig.add_trace(go.Scattermap(
                lat=sel["lat"], lon=sel["lon"], mode="markers",
                marker=dict(size=20, color="#0b0b0b", opacity=0.35),
                hoverinfo="skip", name="selected",
            ))
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=center["lat"], lon=center["lon"]), zoom=11.4),
        clickmode="event",
    )
    return _base_layout(fig, 560)


def build_property_trend(market: pd.DataFrame, zone_slug: str, zone_name: str,
                         property_type: str, asking_m2: float, fair_m2: float) -> go.Figure:
    """Zone median EUR/m2 over time, with this property's asking and fair EUR/m2."""
    df = market[(market["zone"] == zone_slug) & (market["property_type"] == property_type)]
    df = df.sort_values("year")
    fig = go.Figure(
        go.Scatter(
            x=df["year"], y=df["median_price_m2"], mode="lines+markers",
            line=dict(color=SERIES_BLUE, width=2), marker=dict(size=8),
            customdata=df[["n_sales"]],
            hovertemplate="%{x}: zone median %{y:,.0f} €/m² (%{customdata[0]:,} sales)<extra></extra>",
            name="Zone median",
        )
    )
    if not df.empty:
        x0, x1 = df["year"].min(), df["year"].max()
        for value, label, dash in ((asking_m2, "asking", "dot"), (fair_m2, "fair value", "dash")):
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[value, value], mode="lines",
                line=dict(color=INK_MUTED, width=1.5, dash=dash),
                hovertemplate=f"this property — {label}: %{{y:,.0f}} €/m²<extra></extra>",
                name=label,
            ))
            fig.add_annotation(x=x1, y=value, text=f"{label} {value:,.0f}", showarrow=False,
                               xanchor="left", xshift=6, font=dict(size=11, color=INK_MUTED))
    fig.update_xaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED), dtick=1)
    fig.update_yaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED), tickformat=",.0f", ticksuffix=" €")
    fig = _base_layout(fig, 260)
    fig.update_layout(margin=dict(l=8, r=110, t=12, b=8))
    return fig


def build_source_map(points: pd.DataFrame, metric: str | None, bbox: tuple | None,
                     center: dict, big_markers: bool = False,
                     selected_id: str | None = None) -> go.Figure:
    """Records of one data source; colored by its metric (sequential blue) when
    it has one, plus the source's coverage bounding box.

    Expects valued records first (see order_for_map): trace 0 holds records
    with a metric value, trace 1 those without — plotly would otherwise paint
    missing values dark, which reads as an extreme reading.
    """
    missing = points[points["value"].isna()] if metric else points.iloc[0:0]
    points = points[points["value"].notna()] if metric else points
    hover = [
        f"<b>{r.name}</b><br>{r.detail}"
        + (f"<br>{metric}: " + ("–" if pd.isna(r.value) else f"{r.value:,.1f}".replace(",", " "))
           if metric else "")
        for r in points.itertuples()
    ]
    marker = dict(size=26 if big_markers else 8, opacity=0.85 if not big_markers else 0.7)
    if metric and points["value"].notna().any():
        marker.update(
            color=points["value"], colorscale=_ramp_scale(BLUE_RAMP),
            cmin=float(points["value"].quantile(0.02)), cmax=float(points["value"].quantile(0.98)),
            colorbar=dict(title=dict(text=metric, font=dict(size=11, color=INK_MUTED)),
                          thickness=10, outlinewidth=0, tickfont=dict(size=10, color=INK_MUTED),
                          len=0.6, y=0.3),
        )
    else:
        marker.update(color=SERIES_BLUE)
    fig = go.Figure(go.Scattermap(
        lat=points["lat"], lon=points["lon"], mode="markers", marker=marker,
        text=hover, hovertemplate="%{text}<br><i>click for details</i><extra></extra>",
        hoverlabel=dict(bgcolor="#fcfcfb", bordercolor="#c3c2b7", font=dict(color=INK, size=12)),
        name="records",
    ))
    fig.add_trace(go.Scattermap(
        lat=missing["lat"], lon=missing["lon"], mode="markers",
        marker=dict(size=26 if big_markers else 7, color="#c3c2b7", opacity=0.8),
        text=[f"<b>{r.name}</b><br>{r.detail}<br>{metric}: no reading in the latest hour"
              for r in missing.itertuples()],
        hovertemplate="%{text}<br><i>click for details</i><extra></extra>",
        hoverlabel=dict(bgcolor="#fcfcfb", bordercolor="#c3c2b7", font=dict(color=INK, size=12)),
        name="no recent reading",
    ))
    if bbox is not None:
        lat0, lon0, lat1, lon1 = bbox
        fig.add_trace(go.Scattermap(
            lat=[lat0, lat0, lat1, lat1, lat0], lon=[lon0, lon1, lon1, lon0, lon0],
            mode="lines", line=dict(color=INK_MUTED, width=1.5), hoverinfo="skip", name="coverage",
        ))
    if selected_id is not None:
        both = pd.concat([points, missing])
        sel = both[both["id"] == selected_id]
        if not sel.empty:
            fig.add_trace(go.Scattermap(
                lat=sel["lat"], lon=sel["lon"], mode="markers",
                marker=dict(size=(40 if big_markers else 20), color="#0b0b0b", opacity=0.35),
                hoverinfo="skip", name="selected",
            ))
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=center["lat"], lon=center["lon"]), zoom=11.0),
        clickmode="event",
    )
    return _base_layout(fig, 520)


def build_zone_counts(points: pd.DataFrame, zone_names: dict) -> go.Figure:
    counts = points.groupby("zone").size().rename("n").reset_index()
    counts["name"] = counts["zone"].map(zone_names)
    counts = counts.sort_values("n")
    fig = go.Figure(go.Bar(
        x=counts["n"], y=counts["name"], orientation="h",
        marker=dict(color=SERIES_BLUE, cornerradius=4),
        hovertemplate="<b>%{y}</b><br>%{x:,} records<extra></extra>",
    ))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11))
    fig.update_layout(bargap=0.35)
    return _base_layout(fig, 300)


def build_series(df: pd.DataFrame, y: str, title: str, unit: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=df["observed_at"], y=df[y], mode="lines+markers" if len(df) < 40 else "lines",
        line=dict(color=SERIES_BLUE, width=2), marker=dict(size=6),
        hovertemplate=f"%{{x|%a %d %b %H:%M}}<br>%{{y:,.1f}} {unit}<extra></extra>",
    ))
    fig.update_xaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED), rangemode="tozero")
    fig.update_layout(title=dict(text=title, font=dict(size=13)))
    fig = _base_layout(fig, 220)
    fig.update_layout(margin=dict(l=8, r=8, t=36, b=8))
    return fig


def build_market_map(latest: pd.DataFrame, center: dict) -> go.Figure:
    """Zone medians as a priced map — EUR/m2 on the blue sequential ramp."""
    fig = go.Figure(
        go.Scattermap(
            lat=latest["lat"], lon=latest["lon"],
            mode="markers+text",
            text=latest["median_price_m2"].map(lambda v: f"{v/1000:.1f}k€"),
            textfont=dict(size=11, color=INK),
            textposition="top center",
            marker=dict(
                size=34,
                color=latest["median_price_m2"],
                colorscale=_ramp_scale(BLUE_RAMP),
                opacity=0.8,
                colorbar=dict(
                    title=dict(text="€/m²", font=dict(size=12, color=INK_MUTED)),
                    thickness=10, outlinewidth=0,
                    tickfont=dict(size=11, color=INK_MUTED), len=0.5, y=0.25,
                ),
            ),
            customdata=latest[["name", "median_price_m2", "n_sales"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>median %{customdata[1]:,.0f} €/m²<br>"
                "%{customdata[2]:,} sales (last 2 years)<extra>market</extra>"
            ),
        )
    )
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=center["lat"], lon=center["lon"]), zoom=10.8),
    )
    return _base_layout(fig, 480)


def build_market_trend(market: pd.DataFrame, zone_slug: str, zone_name: str,
                       property_type: str) -> go.Figure:
    df = market[(market["zone"] == zone_slug) & (market["property_type"] == property_type)]
    df = df.sort_values("year")
    fig = go.Figure(
        go.Scatter(
            x=df["year"], y=df["median_price_m2"],
            mode="lines+markers",
            line=dict(color=SERIES_BLUE, width=2),
            marker=dict(size=8),
            customdata=df[["n_sales"]],
            hovertemplate="%{x}: %{y:,.0f} €/m² (%{customdata[0]:,} sales)<extra></extra>",
        )
    )
    fig.update_xaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED), dtick=1)
    fig.update_yaxes(gridcolor=GRID, tickfont=dict(color=INK_MUTED), tickformat=",.0f")
    fig.update_layout(title=dict(text=f"Median €/m² — {zone_name} ({property_type})", font=dict(size=14)))
    fig = _base_layout(fig, 300)
    fig.update_layout(margin=dict(t=42))
    return fig


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
