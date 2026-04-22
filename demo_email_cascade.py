"""Integration demo of the email → gravatar → enrichment cascade.

Starting from just an email address, the system should automatically:
  1. Extract the domain (flagging disposable providers).
  2. Check Gravatar — if one exists, emit an Account(platform="gravatar").
  3. The Account triggers ProfileEnrichment, which fetches the Gravatar
     profile JSON and extracts all the cross-linked accounts, URLs,
     location, display name, etc.
  4. The avatar URL flows into AvatarHashCollector, which (given other
     avatars we already hashed) could correlate to other accounts.

We stub the two HTTP endpoints (Gravatar HEAD, Gravatar profile JSON)
so this runs fully offline.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent / "src"))

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.email import (
    EmailDomainExtractor,
    GravatarCollector,
)
from osint_core.collectors.enrichment.fetchers import FetchResult, ProfileFetcher
from osint_core.collectors.enrichment.profile import ProfileEnrichmentCollector
from osint_core.collectors.vision.avatar_hash import AvatarHashCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email
from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization import render_html


class StubFetcher(ProfileFetcher):
    """Returns canned Gravatar profile data — simulates the real API."""

    def __init__(self, canned: dict[str, FetchResult]) -> None:
        self.canned = canned

    async def fetch(self, platform, username, profile_url):
        key = f"{platform}:{username}"
        if key in self.canned:
            return self.canned[key]
        return FetchResult(status=404, fetched_url=profile_url)


async def run_cascade() -> InMemoryGraphStore:
    bus = EventBus()
    store = InMemoryGraphStore()

    async def on_any(event):
        store.add_event(event)

    for t in ("username", "email", "domain", "url", "location",
              "account", "image"):
        bus.subscribe(t, on_any, dedup=False)

    # Compute the MD5 hash of the seed email so we can key our stub
    import hashlib
    seed_email = "alice.martinez@protonmail.com"
    md5 = hashlib.md5(seed_email.encode()).hexdigest()

    # -- Stub HTTP layer ----------------------------------------------------
    # 1) Gravatar existence check
    async def fake_gravatar_exists(self, url):
        return True

    # 2) ProfileEnrichment fetcher — returns a rich canned Gravatar profile
    fake_bio = "\n".join([
        "Alice Martinez",
        "Python developer based in Barcelona, Spain.",
        "https://alice.codes",
        "alice@alice.codes",
        "https://github.com/amartinez",
        "@amartinez",
        "https://twitter.com/alice_writes",
        "@alice_writes",
    ])
    stub_fetcher = StubFetcher({
        f"gravatar:{md5}": FetchResult(
            status=200,
            fetched_url=f"https://www.gravatar.com/{md5}.json",
            bio=fake_bio,
            display_name="Alice Martinez",
            avatar_url="https://secure.gravatar.com/avatar/" + md5,
            extras={"linked_accounts": ["github", "twitter"]},
        ),
    })

    # -- Wire collectors ---------------------------------------------------
    GravatarCollector._gravatar_exists = fake_gravatar_exists  # type: ignore[method-assign]

    GravatarCollector(bus).register()
    EmailDomainExtractor(bus).register()
    ProfileEnrichmentCollector(bus, fetcher=stub_fetcher).register()

    async def fake_avatar_download(self, url):
        # Returns a stable fake hash so correlations are deterministic
        return (0xCAFEBABE12345678, "fake_sha256", 256, 256)

    AvatarHashCollector._download_and_hash = fake_avatar_download  # type: ignore[method-assign]
    AvatarHashCollector(bus, relationship_sink=store).register()

    # -- Seed and run -------------------------------------------------------
    seed = Email(
        value=seed_email,
        evidence=[Evidence(collector="user_input", confidence=1.0,
                           notes="Investigation seed")],
    )
    store.add_entity(seed)
    await bus.publish(EntityDiscovered(entity=seed, origin_collector="user_input"))
    await bus.drain()
    return store


def main() -> None:
    store = asyncio.run(run_cascade())

    print("Summary:", store.summary())
    print()
    for entity_type in ("email", "domain", "account", "url", "location",
                        "username", "image"):
        entities = store.by_type(entity_type)
        if not entities:
            continue
        print(f"  {entity_type}:")
        for e in entities:
            evidence_collectors = ", ".join(
                sorted({ev.collector for ev in e.evidence})
            )
            print(f"    - {e.value}  [{evidence_collectors}]")
        print()
    print(f"Relations: {len(store.relationships)}")
    preds = {}
    for r in store.relationships:
        preds[r.predicate] = preds.get(r.predicate, 0) + 1
    for p, c in preds.items():
        print(f"    - {p}: {c}")

    html = render_html(store, target="alice.martinez@protonmail.com")
    out = Path("/mnt/user-data/outputs/email_cascade_demo.html")
    out.write_text(html, encoding="utf-8")
    print(f"\nGraph rendered to {out}")


if __name__ == "__main__":
    main()
