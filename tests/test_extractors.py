"""Tests for the text extractors — bread and butter of enrichment."""

from osint_core.collectors.enrichment.extractors import (
    EmailExtractor,
    HandleExtractor,
    LocationExtractor,
    UrlExtractor,
)


# ---------------------------------------------------------------------------
# EmailExtractor
# ---------------------------------------------------------------------------


def test_email_extractor_finds_simple_email() -> None:
    ex = EmailExtractor()
    results = list(ex.extract("Contact: alice@example.com", {}))
    assert len(results) == 1
    entity, conf = results[0]
    assert entity.value == "alice@example.com"
    assert conf == 0.80


def test_email_extractor_dedups_case_insensitively() -> None:
    ex = EmailExtractor()
    results = list(ex.extract("Alice@Example.COM and alice@example.com", {}))
    assert len(results) == 1


def test_email_extractor_handles_plus_addressing() -> None:
    ex = EmailExtractor()
    results = list(ex.extract("reach me: bob+osint@gmail.com", {}))
    assert results[0][0].value == "bob+osint@gmail.com"


def test_email_extractor_ignores_garbage() -> None:
    ex = EmailExtractor()
    results = list(ex.extract("not @ an email, and @@@", {}))
    assert results == []


def test_email_extractor_finds_multiple() -> None:
    ex = EmailExtractor()
    text = "alice@foo.com, bob@bar.org, also carol@baz.io"
    values = {e.value for e, _ in ex.extract(text, {})}
    assert values == {"alice@foo.com", "bob@bar.org", "carol@baz.io"}


# ---------------------------------------------------------------------------
# UrlExtractor
# ---------------------------------------------------------------------------


def test_url_extractor_finds_https() -> None:
    ex = UrlExtractor()
    results = list(ex.extract("My blog: https://example.com/me", {}))
    assert len(results) == 1
    assert results[0][0].value == "https://example.com/me"


def test_url_extractor_strips_trailing_punctuation() -> None:
    ex = UrlExtractor()
    results = list(ex.extract("check https://example.com.", {}))
    assert results[0][0].value == "https://example.com"


def test_url_extractor_excludes_profile_url() -> None:
    ex = UrlExtractor()
    context = {"profile_url": "https://github.com/alice"}
    text = "Profile: https://github.com/alice/ and blog: https://alice.dev"
    values = {e.value for e, _ in ex.extract(text, context)}
    assert "https://github.com/alice" not in values
    assert "https://alice.dev" in values


def test_url_extractor_dedups() -> None:
    ex = UrlExtractor()
    text = "Twice: https://a.com and again https://a.com"
    results = list(ex.extract(text, {}))
    assert len(results) == 1


# ---------------------------------------------------------------------------
# HandleExtractor
# ---------------------------------------------------------------------------


def test_handle_extractor_finds_mentions() -> None:
    ex = HandleExtractor()
    text = "Follow @alice_dev and @bob-code... wait no @bob_code"
    values = {e.value for e, _ in ex.extract(text, {})}
    assert "alice_dev" in values
    assert "bob_code" in values


def test_handle_extractor_skips_origin() -> None:
    ex = HandleExtractor()
    context = {"username": "alice"}
    text = "I am @alice and also @other"
    values = {e.value for e, _ in ex.extract(text, context)}
    assert "alice" not in values  # skipped because it's us
    assert "other" in values


def test_handle_extractor_avoids_email_false_positives() -> None:
    ex = HandleExtractor()
    # "@example.com" inside "alice@example.com" should not match as a handle
    text = "alice@example.com"
    values = {e.value for e, _ in ex.extract(text, {})}
    assert values == set()


def test_handle_extractor_filters_common_noise() -> None:
    ex = HandleExtractor()
    text = "Email @me or hit @admin"
    values = {e.value for e, _ in ex.extract(text, {})}
    assert "me" not in values
    assert "admin" not in values


# ---------------------------------------------------------------------------
# LocationExtractor
# ---------------------------------------------------------------------------


def test_location_extractor_case_insensitive() -> None:
    ex = LocationExtractor()
    results = list(ex.extract("Based in paris, France", {}))
    values = {e.value for e, _ in results}
    assert "Paris" in values


def test_location_extractor_dedups() -> None:
    ex = LocationExtractor()
    text = "Paris is home. I love Paris."
    results = list(ex.extract(text, {}))
    assert len(results) == 1


def test_location_extractor_populates_country() -> None:
    ex = LocationExtractor()
    [(loc, _)] = list(ex.extract("Working in Berlin", {}))
    assert loc.city == "Berlin"
    assert loc.country == "DE"


def test_location_extractor_multi_word_locations() -> None:
    ex = LocationExtractor()
    results = list(ex.extract("from San Francisco to New York", {}))
    values = {e.value for e, _ in results}
    assert "San Francisco" in values
    assert "New York" in values


def test_location_extractor_avoids_substring_matches() -> None:
    """Word-boundary matching: 'Osloite' must not match 'Oslo'."""
    ex = LocationExtractor()
    results = list(ex.extract("the Osloite collective", {}))
    assert results == []


def test_location_extractor_custom_gazetteer() -> None:
    ex = LocationExtractor(
        gazetteer={"Atlantis": {"city": "Atlantis", "country": "XX"}}
    )
    [(loc, _)] = list(ex.extract("I live in Atlantis", {}))
    assert loc.country == "XX"
