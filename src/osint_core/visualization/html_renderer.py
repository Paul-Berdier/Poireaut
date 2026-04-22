"""Render a self-contained HTML graph viewer from an investigation store."""

from __future__ import annotations

import json
from importlib import resources

from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization.graph_export import ENTITY_COLORS, export_cytoscape


def _load_template() -> str:
    return resources.files("osint_core.visualization").joinpath(
        "template.html"
    ).read_text(encoding="utf-8")


def render_html(store: InMemoryGraphStore, target: str = "") -> str:
    """Render a standalone, interactive HTML page visualizing the investigation.

    The output file has no external dependencies beyond two CDN scripts
    (Cytoscape.js + a layout plugin) and Google Fonts. It can be emailed,
    attached to a report, or archived as-is.
    """
    data = export_cytoscape(store, target=target)
    template = _load_template()
    summary = data["summary"]
    entity_count = sum(v for k, v in summary.items() if k != "relationships")
    edge_count = summary.get("relationships", 0)
    return (
        template.replace("__TARGET__", target or "unknown")
        .replace("__ENTITY_COUNT__", str(entity_count))
        .replace("__EDGE_COUNT__", str(edge_count))
        .replace('"__DATA_JSON__"', json.dumps(data))
        .replace('"__TYPE_COLORS_JSON__"', json.dumps(ENTITY_COLORS))
    )
