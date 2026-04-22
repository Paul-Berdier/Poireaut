"""Tests for the entity model."""

import pytest

from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain, Email, Phone, Url, Username
from osint_core.entities.profiles import Account


def test_username_keeps_case_but_lowers_dedup_key() -> None:
    u = Username(value="JDupont")
    assert u.value == "JDupont"
    assert u.dedup_key() == "username:jdupont"


def test_email_is_lowercased_and_validated() -> None:
    e = Email(value="John.Doe@Example.COM ")
    assert e.value == "john.doe@example.com"
    assert e.local_part == "john.doe"
    assert e.domain_part == "example.com"


def test_invalid_email_rejected() -> None:
    with pytest.raises(ValueError):
        Email(value="not-an-email")


def test_phone_normalization_keeps_plus() -> None:
    assert Phone(value="+33 6 12 34 56 78").value == "+33612345678"
    assert Phone(value="(415) 555-0199").value == "4155550199"


def test_domain_strips_scheme_and_www() -> None:
    assert Domain(value="https://www.Example.com/some/path").value == "example.com"


def test_domain_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        Domain(value="not a domain")


def test_url_requires_scheme() -> None:
    with pytest.raises(ValueError):
        Url(value="example.com")
    assert Url(value="https://example.com").value == "https://example.com"


def test_confidence_aggregates_to_max() -> None:
    u = Username(
        value="alice",
        evidence=[
            Evidence(collector="a", confidence=0.3),
            Evidence(collector="b", confidence=0.9),
            Evidence(collector="c", confidence=0.5),
        ],
    )
    assert u.confidence == 0.9


def test_confidence_zero_when_no_evidence() -> None:
    assert Username(value="alice").confidence == 0.0


def test_merge_combines_evidence_and_metadata() -> None:
    a = Username(
        value="alice",
        evidence=[Evidence(collector="a", confidence=0.5)],
        metadata={"first_source": "x"},
    )
    b = Username(
        value="alice",
        evidence=[Evidence(collector="b", confidence=0.9)],
        metadata={"second_source": "y"},
    )
    a.merge(b)
    assert len(a.evidence) == 2
    assert a.confidence == 0.9
    assert a.metadata == {"first_source": "x", "second_source": "y"}


def test_merge_rejects_distinct_entities() -> None:
    a = Username(value="alice")
    b = Username(value="bob")
    with pytest.raises(ValueError):
        a.merge(b)


def test_merge_fills_in_none_fields() -> None:
    """When a field is None on self but set on other, it should be upgraded."""
    from osint_core.entities.profiles import Account

    a = Account(value="github:alice", platform="github", username="alice")
    assert a.display_name is None
    b = Account(
        value="github:alice",
        platform="github",
        username="alice",
        display_name="Alice Example",
        avatar_url="https://img/alice.png",
        followers_count=42,
    )
    a.merge(b)
    assert a.display_name == "Alice Example"
    assert a.avatar_url == "https://img/alice.png"
    assert a.followers_count == 42


def test_merge_does_not_overwrite_existing_fields() -> None:
    """Already-set fields are never clobbered, even by newer evidence."""
    from osint_core.entities.profiles import Account

    a = Account(
        value="github:alice",
        platform="github",
        username="alice",
        display_name="Alice First",
    )
    b = Account(
        value="github:alice",
        platform="github",
        username="alice",
        display_name="Alice Second",  # should NOT overwrite
    )
    a.merge(b)
    assert a.display_name == "Alice First"


def test_account_dedup_key_includes_platform() -> None:
    gh = Account(value="github:alice", platform="github", username="alice")
    rd = Account(value="reddit:alice", platform="reddit", username="alice")
    assert gh.dedup_key() != rd.dedup_key()
