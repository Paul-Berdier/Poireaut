"""Integration demo: real Pillow-generated avatars flowing through the
AvatarHashCollector to produce a correlated investigation graph.

We generate 5 synthetic avatars:
  - alpha (github + gitlab): identical image → should correlate perfectly
  - beta  (github + reddit): same base image, re-encoded → should correlate
  - gamma (keybase):         unrelated image → no correlation

Each account is fed to the bus as if enrichment had just upgraded it
with an avatar URL. We verify the graph contains the expected
same_avatar_as edges with proper confidence scores, then render the
HTML for visual inspection.
"""

import asyncio
import hashlib
import io
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from PIL import Image, ImageDraw

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.vision.avatar_hash import AvatarHashCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Username
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization import render_html


def _make_avatar(seed: int, jitter: float = 0.0) -> bytes:
    """Produce a distinctive 128x128 PNG with a reproducible pattern.

    `jitter` slightly perturbs pixels so re-encoded/"similar" variants
    differ from originals by a few bits of pHash but remain recognizable.
    """
    rng = random.Random(seed)
    img = Image.new("RGB", (128, 128), color=(20, 28, 40))
    draw = ImageDraw.Draw(img)
    # Large colored circles as distinctive features
    for _ in range(6):
        x, y = rng.randint(10, 118), rng.randint(10, 118)
        r = rng.randint(12, 30)
        color = (rng.randint(80, 255), rng.randint(60, 255), rng.randint(40, 200))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
    # Stripes
    for i in range(0, 128, 12):
        draw.line([(0, i), (128, i)], fill=(255, 255, 255, 80), width=1)

    if jitter > 0:
        # Add noise + re-encode at lower quality to simulate a platform's
        # avatar pipeline modifying the bytes while keeping the look.
        import numpy as np

        try:
            arr = np.array(img, dtype=np.int16)
            noise = np.random.RandomState(seed).normal(0, jitter * 255, arr.shape).astype(np.int16)
            arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)
        except ImportError:
            pass  # numpy optional; without it, jitter is a no-op

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85 if jitter else 95)
    return buf.getvalue()


async def run_demo() -> InMemoryGraphStore:
    # 1) Generate our canned avatar byte dictionary
    alpha_bytes = _make_avatar(seed=42)
    beta_bytes = _make_avatar(seed=7)
    beta_rencoded = _make_avatar(seed=7, jitter=0.02)  # same but perturbed
    gamma_bytes = _make_avatar(seed=999)

    url_to_bytes: dict[str, bytes] = {
        "https://img/github/alpha.png":  alpha_bytes,
        "https://img/gitlab/alpha.png":  alpha_bytes,       # byte-identical
        "https://img/github/beta.png":   beta_bytes,
        "https://img/reddit/beta.png":   beta_rencoded,     # same look, new bytes
        "https://img/keybase/gamma.png": gamma_bytes,
    }

    # 2) Wire the system
    bus = EventBus()
    store = InMemoryGraphStore()

    async def on_any(event):
        store.add_event(event)

    for t in ("username", "account", "image"):
        bus.subscribe(t, on_any, dedup=False)

    collector = AvatarHashCollector(bus, relationship_sink=store)

    # Stub the download to use our in-memory bytes — same code path from that point
    import imagehash
    from PIL import Image

    async def fake_download(url):
        if url not in url_to_bytes:
            return None
        img_bytes = url_to_bytes[url]
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        phash_int = int(str(imagehash.phash(img, hash_size=8)), 16)
        sha = hashlib.sha256(img_bytes).hexdigest()
        return phash_int, sha, img.width, img.height

    collector._download_and_hash = fake_download
    collector.register()

    # 3) Seed a target
    seed = Username(
        value="alicepaterson",
        evidence=[Evidence(collector="user_input", confidence=1.0)],
    )
    store.add_entity(seed)
    await bus.publish(
        EntityDiscovered(entity=seed, origin_collector="user_input")
    )

    # 4) Publish accounts one by one (as enrichment would)
    accounts_spec = [
        ("github",  "alicepaterson", "https://img/github/alpha.png"),
        ("gitlab",  "alicepaterson", "https://img/gitlab/alpha.png"),
        ("github",  "ap_writes",     "https://img/github/beta.png"),
        ("reddit",  "alice_p",       "https://img/reddit/beta.png"),
        ("keybase", "alicepaterson", "https://img/keybase/gamma.png"),
    ]
    for platform, username, url in accounts_spec:
        acc = Account(
            value=f"{platform}:{username}",
            platform=platform,
            username=username,
            profile_url=f"https://{platform}.com/{username}",
            display_name=None,
            avatar_url=url,
            evidence=[Evidence(
                collector="profile_enrichment",
                confidence=0.9,
                source_url=f"https://api.{platform}.com/users/{username}",
                notes="Account upgraded with avatar_url",
            )],
        )
        store.add_entity(acc)
        await bus.publish(
            EntityDiscovered(
                entity=acc,
                origin_collector="profile_enrichment",
                origin_entity_id=seed.id,
            )
        )

    await bus.drain()
    return store


def main() -> None:
    store = asyncio.run(run_demo())

    same_avatar = [r for r in store.relationships if r.predicate == "same_avatar_as"]
    derived = [r for r in store.relationships if r.predicate == "derived_from"]

    print(f"Entities: {store.summary()}")
    print(f"derived_from edges: {len(derived)}")
    print(f"same_avatar_as edges: {len(same_avatar)}")
    for r in same_avatar:
        d = r.metadata.get("hamming_distance", "?")
        mt = r.metadata.get("match_type", "?")
        conf = r.evidence[0].confidence if r.evidence else "?"
        print(f"  · pHash-distance={d} ({mt}, conf={conf}): {r.source_id} ↔ {r.target_id}")

    html = render_html(store, target="alicepaterson")
    out = Path("/mnt/user-data/outputs/avatar_correlation_demo.html")
    out.write_text(html, encoding="utf-8")
    print(f"\nGraph rendered to {out}")


if __name__ == "__main__":
    main()
