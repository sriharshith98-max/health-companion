"""Longitudinal laboratory test trends and visualization module for Second-Opinion Companion.

Aggregates repeat test measurements over time and generates interactive Plotly figures.
"""

from collections import defaultdict
import logging
from typing import Any
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


def extract_lab_series(labs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group lab measurements by test name, ordered by date."""
    series_map = defaultdict(list)
    for entry in labs:
        test_name = entry.get("test") or entry.get("normalized_test")
        if not test_name:
            continue
        val = entry.get("value")
        try:
            num_val = float(val)
        except (ValueError, TypeError):
            continue  # Skip qualitative non-numeric entries for trend graphing

        date_str = entry.get("date", "Initial")
        series_map[test_name].append({
            "date": date_str,
            "value": num_val,
            "unit": entry.get("unit", ""),
            "status": entry.get("status", "NORMAL"),
            "ref_low": entry.get("ref_low") or entry.get("effective_ref_low"),
            "ref_high": entry.get("ref_high") or entry.get("effective_ref_high"),
        })

    return series_map


def build_lab_trend_figures(labs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build Plotly chart objects for each laboratory test with repeated readings (>= 2).

    Returns:
        List of dicts: [{'test': str, 'figure': go.Figure, 'count': int}]
    """
    series_map = extract_lab_series(labs)
    results = []

    for test_name, readings in series_map.items():
        if len(readings) < 2:
            continue  # Only plot trends when 2 or more measurements exist

        readings_sorted = sorted(readings, key=lambda r: str(r["date"]))
        dates = [r["date"] for r in readings_sorted]
        values = [r["value"] for r in readings_sorted]
        units = readings_sorted[0].get("unit", "")
        statuses = [r["status"] for r in readings_sorted]

        # Colors based on status
        marker_colors = []
        for s in statuses:
            if s == "CRITICAL":
                marker_colors.append("#EF4444")
            elif s in ("LOW", "HIGH"):
                marker_colors.append("#F59E0B")
            else:
                marker_colors.append("#2563EB")

        fig = go.Figure()

        # Add trajectory line and points
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=values,
                mode="lines+markers+text",
                name=test_name.title(),
                line=dict(color="#2563EB", width=3),
                marker=dict(size=12, color=marker_colors, line=dict(width=2, color="#FFFFFF")),
                text=[f"{v} {units}" for v in values],
                textposition="top center",
                hovertemplate="<b>Date</b>: %{x}<br><b>Value</b>: %{y} " + units + "<extra></extra>",
            )
        )

        # Add reference range horizontal lines if available
        ref_low = readings_sorted[0].get("ref_low")
        ref_high = readings_sorted[0].get("ref_high")
        if ref_low is not None and ref_high is not None:
            fig.add_hline(
                y=float(ref_low),
                line_dash="dot",
                line_color="#10B981",
                annotation_text=f"Ref Low ({ref_low})",
                annotation_position="bottom right",
            )
            fig.add_hline(
                y=float(ref_high),
                line_dash="dot",
                line_color="#10B981",
                annotation_text=f"Ref High ({ref_high})",
                annotation_position="top right",
            )

        fig.update_layout(
            title=dict(
                text=f"Longitudinal Trend: {test_name.replace('_', ' ').title()} ({units})",
                font=dict(size=16, color="#0F172A", family="Plus Jakarta Sans, sans-serif"),
            ),
            xaxis=dict(title="Report Date / Visit", showgrid=True, gridcolor="#F1F5F9"),
            yaxis=dict(title=f"Value ({units})", showgrid=True, gridcolor="#F1F5F9"),
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            margin=dict(l=40, r=40, t=50, b=40),
            height=340,
        )

        results.append({
            "test": test_name,
            "figure": fig,
            "count": len(readings),
        })

    return results
