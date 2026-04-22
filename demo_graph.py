"""Generate a demo HTML graph with realistic enriched data.

This script bypasses HTTP entirely and hand-crafts a store that looks like
what a real `osint investigate alice --maigret --enrich` run would produce
on an active developer profile. It demonstrates the full power of the
viewer: multiple accounts, enrichment cascading into sub-entities, and
the provenance graph.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from osint_core.bus.events import EntityDiscovered
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email, Url, Username
from osint_core.entities.profiles import Account, Location
from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization import render_html


def build_demo_store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()

    # Seed
    seed = store.add_entity(
        Username(
            value="alice_dev",
            evidence=[Evidence(collector="user_input", confidence=1.0,
                               notes="Investigation seed")],
        )
    )

    # Accounts found by Maigret
    accounts_spec = [
        ("github",       "Software engineer, OSS contributor",  0.95, True),
        ("gitlab",       "",                                    0.90, True),
        ("keybase",      "",                                    0.90, False),
        ("reddit",       "",                                    0.80, False),
        ("dev.to",       "",                                    0.80, False),
        ("stackoverflow","",                                    0.75, False),
        ("mastodon",     "",                                    0.70, False),
        ("lobsters",     "",                                    0.70, False),
    ]
    account_entities: list[Account] = []
    for platform, bio, conf, enriched in accounts_spec:
        acc_data = {
            "value": f"{platform}:alice_dev",
            "platform": platform,
            "username": "alice_dev",
            "profile_url": f"https://{platform}.com/alice_dev",
            "evidence": [Evidence(collector="maigret", confidence=conf,
                                  notes=f"Maigret matched on {platform}")],
        }
        if enriched:
            acc_data["display_name"] = "Alice Martinez"
            acc_data["bio"] = bio
            acc_data["avatar_url"] = f"https://{platform}.com/avatar/alice_dev.png"
            acc_data["followers_count"] = {"github": 342, "gitlab": 58}.get(platform)
        acc = Account(**acc_data)
        store.add_event(
            EntityDiscovered(entity=acc, origin_collector="maigret",
                             origin_entity_id=seed.id)
        )
        account_entities.append(store.by_type("account")[-1])

    # Enrichment emits on the github account
    github_acc = [a for a in account_entities if a.platform == "github"][0]

    # Email extracted from GitHub bio
    store.add_event(
        EntityDiscovered(
            entity=Email(
                value="alice.martinez@protonmail.com",
                evidence=[Evidence(collector="profile_enrichment", confidence=0.80,
                                   source_url="https://api.github.com/users/alice_dev",
                                   notes="extracted by email from github bio of alice_dev",
                                   raw_data={"extractor": "email", "source_account": "github:alice_dev"})],
            ),
            origin_collector="profile_enrichment",
            origin_entity_id=github_acc.id,
        )
    )

    # Blog URL from github.blog field
    store.add_event(
        EntityDiscovered(
            entity=Url(
                value="https://alice.codes",
                evidence=[Evidence(collector="profile_enrichment", confidence=0.85,
                                   source_url="https://api.github.com/users/alice_dev",
                                   notes="extracted by url from github bio of alice_dev")],
            ),
            origin_collector="profile_enrichment",
            origin_entity_id=github_acc.id,
        )
    )

    # Location extracted from bio
    store.add_event(
        EntityDiscovered(
            entity=Location(
                value="Barcelona",
                city="Barcelona",
                country="ES",
                evidence=[Evidence(collector="profile_enrichment", confidence=0.55,
                                   source_url="https://api.github.com/users/alice_dev",
                                   notes="extracted by location from github bio of alice_dev")],
            ),
            origin_collector="profile_enrichment",
            origin_entity_id=github_acc.id,
        )
    )

    # Handle mention discovered in bio — another username to investigate
    store.add_event(
        EntityDiscovered(
            entity=Username(
                value="amartinez",
                evidence=[Evidence(collector="profile_enrichment", confidence=0.40,
                                   source_url="https://api.github.com/users/alice_dev",
                                   notes="extracted by handle from github bio of alice_dev")],
            ),
            origin_collector="profile_enrichment",
            origin_entity_id=github_acc.id,
        )
    )

    # And on the gitlab account — confirms the same email (evidence stacks!)
    gitlab_acc = [a for a in account_entities if a.platform == "gitlab"][0]
    store.add_event(
        EntityDiscovered(
            entity=Email(
                value="alice.martinez@protonmail.com",
                evidence=[Evidence(collector="profile_enrichment", confidence=0.75,
                                   source_url="https://gitlab.com/api/v4/users?username=alice_dev",
                                   notes="extracted by email from gitlab bio of alice_dev")],
            ),
            origin_collector="profile_enrichment",
            origin_entity_id=gitlab_acc.id,
        )
    )

    return store


if __name__ == "__main__":
    store = build_demo_store()
    target = "alice_dev"
    html = render_html(store, target=target)
    output = Path("/mnt/user-data/outputs/alice_investigation.html")
    output.write_text(html, encoding="utf-8")
    print(f"Graph rendered to {output}")
    print(f"Summary: {store.summary()}")
