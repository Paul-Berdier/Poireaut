"""Convert an investigation store into Cytoscape.js elements.

This is pure data transformation — no HTML, no files. Returns a dict
that the HTML renderer (or any other consumer — Neo4j import, D3,
sigma.js) can turn into a visualization.
"""

from __future__ import annotations

from typing import Any

from osint_core.entities.base import Entity
from osint_core.storage.memory import InMemoryGraphStore


# Entity type → palette entry. Kept in one place so the HTML template
# and Python code never disagree on colors.
ENTITY_COLORS: dict[str, str] = {
    "username": "#4a9eff",    # electric blue (the origin type)
    "account":  "#00d4a0",    # teal
    "email":    "#ffa726",    # amber
    "url":      "#b39ddb",    # dusty lavender
    "location": "#ef5350",    # coral red
    "phone":    "#4dd0e1",    # cyan
    "person":   "#fff59d",    # pale gold
    "domain":   "#aed581",    # sage
    "ip":       "#aed581",    # same family as domain
    "image":    "#ce93d8",    # soft violet
}

_LABEL_MAX = 40


def _label(entity: Entity) -> str:
    """Human-facing short label for a node."""
    if entity.entity_type == "account":
        # Accounts store a compound value "platform:username" — show platform only
        platform = getattr(entity, "platform", None)
        username = getattr(entity, "username", None)
        if platform and username:
            text = f"{platform} · {username}"
        else:
            text = entity.value
    else:
        text = entity.value
    return text if len(text) <= _LABEL_MAX else text[: _LABEL_MAX - 1] + "…"


def export_cytoscape(
    store: InMemoryGraphStore,
    target: str = "",
) -> dict[str, Any]:
    """Transform a store into a Cytoscape.js-ready dict.

    The returned structure is JSON-serializable and self-contained: the HTML
    renderer embeds it verbatim into the output page as a JS constant.
    """
    nodes: list[dict[str, Any]] = []
    for e in store.all():
        nodes.append(
            {
                "data": {
                    "id": str(e.id),
                    "label": _label(e),
                    "value": e.value,
                    "type": e.entity_type,
                    "confidence": round(e.confidence, 3),
                    "color": ENTITY_COLORS.get(e.entity_type, "#888888"),
                    "evidence_count": len(e.evidence),
                    "is_seed": bool(target) and e.value.lower() == target.lower(),
                    # Full entity payload — feeds the right-side details panel
                    "entity": e.model_dump(mode="json"),
                }
            }
        )

    edges: list[dict[str, Any]] = []
    for r in store.relationships:
        edges.append(
            {
                "data": {
                    "id": str(r.id),
                    "source": str(r.source_id),
                    "target": str(r.target_id),
                    "predicate": r.predicate,
                    "relationship": r.model_dump(mode="json"),
                }
            }
        )

    return {
        "target": target,
        "summary": store.summary(),
        "nodes": nodes,
        "edges": edges,
    }
