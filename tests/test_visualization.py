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


# ---------------------------------------------------------------------------
# Edge-predicate legend and per-predicate Cytoscape styles
# ---------------------------------------------------------------------------


def test_render_html_contains_edge_legend_block() -> None:
    store = _populate_store()
    html = render_html(store, target="alice")
    # The HTML scaffold for the predicate legend must be present even when
    # no exotic predicates exist in the investigation.
    assert 'id="edge-legend"' in html
    assert 'id="edge-legend-list"' in html
    assert "renderEdgeLegend" in html


def test_render_html_has_styles_for_new_predicates() -> None:
    """All new predicates should have a Cytoscape style block so they render
    with their semantic color/dash pattern rather than the neutral fallback."""
    store = _populate_store()
    html = render_html(store, target="alice")
    for predicate in (
        "same_avatar_as",
        "pgp_bound_to",
        "cross_verified_by",
        "commits_as",
        "subdomain_of",
        "same_bio_as",
    ):
        assert f'predicate = "{predicate}"' in html, (
            f"Cytoscape style for {predicate} missing from template"
        )


def test_render_html_lists_predicate_labels() -> None:
    store = _populate_store()
    html = render_html(store, target="alice")
    # The PREDICATE_LABELS map drives the legend text; its presence is what
    # guarantees human-readable labels show up.
    assert "PREDICATE_LABELS" in html
    assert "cross-verified" in html
    assert "PGP key bond" in html


def test_custom_predicates_flow_through_export() -> None:
    """Relationships with new predicates round-trip through export_cytoscape."""
    from osint_core.entities.graph import Relationship

    store = _populate_store()
    accounts = store.by_type("account")
    emails = store.by_type("email")
    assert accounts and emails

    # Attach one representative edge per new predicate.
    edges_to_add = [
        ("cross_verified_by", accounts[0].id, accounts[0].id),
        ("pgp_bound_to", emails[0].id, emails[0].id),
        ("commits_as", accounts[0].id, emails[0].id),
    ]
    for predicate, src, tgt in edges_to_add:
        store.add_relationship(
            Relationship(
                source_id=src,
                target_id=tgt,
                predicate=predicate,
                evidence=[Evidence(collector="test", confidence=0.9)],
            )
        )

    data = export_cytoscape(store, target="alice")
    predicates_in_export = {e["data"]["predicate"] for e in data["edges"]}
    for predicate, _, _ in edges_to_add:
        assert predicate in predicates_in_export
