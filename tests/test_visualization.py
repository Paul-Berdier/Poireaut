"""Tests for the visualization layer: Cytoscape export and HTML render."""

from osint_core.bus.events import EntityDiscovered
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email, Username
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization import ENTITY_COLORS, export_cytoscape, render_html


def _populate_store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    seed = store.add_entity(
        Username(
            value="alice",
            evidence=[Evidence(collector="user_input", confidence=1.0)],
        )
    )
    store.add_event(
        EntityDiscovered(
            entity=Account(
                value="github:alice",
                platform="github",
                username="alice",
                display_name="Alice Example",
                evidence=[Evidence(collector="maigret", confidence=0.9)],
            ),
            origin_collector="maigret",
            origin_entity_id=seed.id,
        )
    )
    store.add_event(
        EntityDiscovered(
            entity=Email(
                value="alice@example.com",
                evidence=[Evidence(collector="profile_enrichment", confidence=0.8)],
            ),
            origin_collector="profile_enrichment",
            origin_entity_id=list(store.by_type("account"))[0].id,
        )
    )
    return store


def test_export_has_expected_shape() -> None:
    store = _populate_store()
    data = export_cytoscape(store, target="alice")
    assert data["target"] == "alice"
    assert set(data.keys()) == {"target", "summary", "nodes", "edges"}
    assert len(data["nodes"]) == 3
    # We created 2 derived_from edges
    assert len(data["edges"]) == 2


def test_node_data_contains_required_fields() -> None:
    store = _populate_store()
    data = export_cytoscape(store, target="alice")
    for node in data["nodes"]:
        d = node["data"]
        assert "id" in d
        assert "label" in d
        assert "value" in d
        assert "type" in d
        assert "color" in d
        assert "confidence" in d
        assert "is_seed" in d
        assert "entity" in d


def test_seed_flag_marks_the_target_node() -> None:
    store = _populate_store()
    data = export_cytoscape(store, target="alice")
    seeds = [n for n in data["nodes"] if n["data"]["is_seed"]]
    assert len(seeds) == 1
    assert seeds[0]["data"]["value"] == "alice"


def test_node_colors_match_palette() -> None:
    store = _populate_store()
    data = export_cytoscape(store, target="alice")
    for node in data["nodes"]:
        expected = ENTITY_COLORS.get(node["data"]["type"])
        assert node["data"]["color"] == expected


def test_account_label_is_friendly() -> None:
    store = _populate_store()
    data = export_cytoscape(store, target="alice")
    account_nodes = [n for n in data["nodes"] if n["data"]["type"] == "account"]
    assert account_nodes[0]["data"]["label"] == "github · alice"


def test_edges_have_source_and_target() -> None:
    store = _populate_store()
    data = export_cytoscape(store, target="alice")
    for edge in data["edges"]:
        d = edge["data"]
        assert "source" in d and "target" in d
        assert "predicate" in d
        assert d["predicate"] == "derived_from"


def test_render_html_produces_valid_page() -> None:
    store = _populate_store()
    html = render_html(store, target="alice")
    # Basic smoke-test: looks like HTML, contains our data, uses our fonts
    assert html.startswith("<!DOCTYPE html>")
    assert "alice" in html
    assert "Fraunces" in html
    assert "JetBrains Mono" in html
    assert "cytoscape" in html.lower()
    # Data should be interpolated as JSON
    assert '"nodes"' in html
    assert '"edges"' in html
    # The template placeholders must all be replaced
    assert "__TARGET__" not in html
    assert "__DATA_JSON__" not in html
    assert "__ENTITY_COUNT__" not in html
    assert "__EDGE_COUNT__" not in html


def test_render_html_no_target() -> None:
    store = _populate_store()
    # Works even without a target (renders "unknown")
    html = render_html(store, target="")
    assert "unknown" in html
