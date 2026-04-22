"""Tests for the in-memory graph store."""

from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Username
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


def test_add_then_get_by_id() -> None:
    store = InMemoryGraphStore()
    u = Username(value="alice")
    store.add_entity(u)
    assert store.get(u.id) is u


def test_upsert_merges_evidence() -> None:
    store = InMemoryGraphStore()
    store.add_entity(
        Username(value="alice", evidence=[Evidence(collector="a", confidence=0.3)])
    )
    store.add_entity(
        Username(value="alice", evidence=[Evidence(collector="b", confidence=0.9)])
    )
    assert len(store) == 1
    [u] = store.by_type("username")
    assert len(u.evidence) == 2
    assert u.confidence == 0.9


def test_by_type_filters() -> None:
    store = InMemoryGraphStore()
    store.add_entity(Username(value="alice"))
    store.add_entity(Account(value="github:alice", platform="github", username="alice"))
    assert len(store.by_type("username")) == 1
    assert len(store.by_type("account")) == 1


def test_summary_counts_by_type() -> None:
    store = InMemoryGraphStore()
    store.add_entity(Username(value="alice"))
    store.add_entity(Account(value="github:alice", platform="github", username="alice"))
    store.add_entity(Account(value="reddit:alice", platform="reddit", username="alice"))
    summary = store.summary()
    assert summary["username"] == 1
    assert summary["account"] == 2
