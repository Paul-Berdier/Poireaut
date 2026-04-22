"""Tests for event-driven storage with auto-relationship creation."""

from uuid import uuid4

from osint_core.bus.events import EntityDiscovered
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Username
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


def _event(entity, collector="test", origin_id=None):
    return EntityDiscovered(
        entity=entity,
        origin_collector=collector,
        origin_entity_id=origin_id,
    )


def test_seed_event_creates_no_relationship() -> None:
    store = InMemoryGraphStore()
    store.add_event(_event(Username(value="alice")))
    assert len(store) == 1
    assert store.relationships == []


def test_origin_id_triggers_edge() -> None:
    store = InMemoryGraphStore()
    u = store.add_entity(Username(value="alice"))
    store.add_event(
        _event(
            Account(value="github:alice", platform="github", username="alice"),
            origin_id=u.id,
        )
    )
    assert len(store.relationships) == 1
    rel = store.relationships[0]
    assert rel.source_id == u.id
    assert rel.predicate == "derived_from"


def test_duplicate_edges_are_dedupped() -> None:
    store = InMemoryGraphStore()
    u = store.add_entity(Username(value="alice"))
    account = Account(value="github:alice", platform="github", username="alice")
    # Same account emitted twice from the same origin
    store.add_event(_event(account, origin_id=u.id))
    store.add_event(_event(account, origin_id=u.id))
    assert len(store.relationships) == 1


def test_edges_from_different_origins_all_recorded() -> None:
    """An account reached via two different paths gets two edges."""
    store = InMemoryGraphStore()
    u1 = store.add_entity(Username(value="alice"))
    u2 = store.add_entity(Username(value="alicedev"))
    account = Account(value="github:alice", platform="github", username="alice")
    store.add_event(_event(account, origin_id=u1.id))
    store.add_event(_event(account, origin_id=u2.id))
    assert len(store.relationships) == 2


def test_self_edge_suppressed_on_merge() -> None:
    """When a collector re-emits an upgraded entity with the same dedup_key
    and the same origin, no self-edge must be created."""
    store = InMemoryGraphStore()
    account = store.add_entity(
        Account(value="github:alice", platform="github", username="alice")
    )
    # Re-emit with the account itself as origin_id (what enrichment does when
    # upgrading). The entity merges into itself — no edge should appear.
    upgraded = Account(
        value="github:alice",
        platform="github",
        username="alice",
        display_name="Alice Example",
    )
    store.add_event(_event(upgraded, origin_id=account.id))
    assert store.relationships == []
    # But the merge still happened
    assert account.display_name == "Alice Example"


def test_relationships_of_returns_incident_edges() -> None:
    store = InMemoryGraphStore()
    u = store.add_entity(Username(value="alice"))
    store.add_event(
        _event(
            Account(value="github:alice", platform="github", username="alice"),
            origin_id=u.id,
        )
    )
    store.add_event(
        _event(
            Account(value="reddit:alice", platform="reddit", username="alice"),
            origin_id=u.id,
        )
    )
    assert len(store.relationships_of(u.id)) == 2


def test_direct_add_relationship_dedups_and_merges_evidence() -> None:
    """Calling add_relationship twice with same (source, target, predicate)
    must not duplicate the edge — evidence merges into the existing one."""
    from osint_core.entities.base import Evidence
    from osint_core.entities.graph import Relationship

    store = InMemoryGraphStore()
    src = uuid4()
    tgt = uuid4()
    r1 = Relationship(
        source_id=src, target_id=tgt, predicate="same_avatar_as",
        evidence=[Evidence(collector="a", confidence=0.8)],
    )
    r2 = Relationship(
        source_id=src, target_id=tgt, predicate="same_avatar_as",
        evidence=[Evidence(collector="b", confidence=0.9)],
    )
    store.add_relationship(r1)
    store.add_relationship(r2)
    assert len(store.relationships) == 1
    assert len(store.relationships[0].evidence) == 2


def test_direct_add_relationship_coexists_with_auto_derived_from() -> None:
    """Auto derived_from from add_event and manual same_avatar_as on the
    same pair of entities should both be stored (different predicates)."""
    from osint_core.entities.base import Evidence
    from osint_core.entities.graph import Relationship

    store = InMemoryGraphStore()
    u = store.add_entity(Username(value="alice"))
    store.add_event(
        _event(
            Account(value="github:alice", platform="github", username="alice"),
            origin_id=u.id,
        )
    )
    acc_id = store.by_type("account")[0].id
    store.add_relationship(
        Relationship(
            source_id=u.id, target_id=acc_id, predicate="same_avatar_as",
            evidence=[Evidence(collector="avatar_hash", confidence=0.9)],
        )
    )
    preds = {r.predicate for r in store.relationships}
    assert preds == {"derived_from", "same_avatar_as"}
