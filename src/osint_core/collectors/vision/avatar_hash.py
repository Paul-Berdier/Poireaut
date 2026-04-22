"""Perceptual-hash based avatar correlation.

The premise: if the same person operates multiple accounts across
platforms, they very often reuse the same profile picture — sometimes
re-exported, re-cropped, or re-compressed, but visually identical. A
perceptual hash (pHash) collapses an image down to a 64-bit fingerprint
where visually similar images map to nearby fingerprints in Hamming space.

Flow
----
1. Subscribe to `account` entities (opting out of bus dedup so we react
   to enrichment upgrading a bare Account with `avatar_url`).
2. Download the avatar bytes, compute sha256 + pHash via Pillow+imagehash.
3. Emit an ImageAsset node — linked to the account by derived_from.
4. Compare against every previously hashed avatar; for pairs whose pHash
   Hamming distance is below threshold, emit a `same_avatar_as`
   relationship between the two Accounts directly. Confidence decays
   with distance.

Thresholds (for 64-bit pHash)
-----------------------------
distance 0–4   → identical-ish (re-encoded, same source) — confidence ≥ 0.9
distance 5–10  → visually similar (crop/edit/resize)     — confidence 0.5–0.8
distance > 10  → probably different — no relationship emitted
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from typing import ClassVar
from uuid import UUID

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.profiles import Account, ImageAsset

log = logging.getLogger(__name__)


class AvatarHashCollector(BaseCollector):
    name = "avatar_hash"
    consumes: ClassVar[list[str]] = ["account"]
    produces: ClassVar[list[str]] = ["image"]
    # Opt out of bus dedup: we need to see the upgraded Account event when
    # enrichment adds an avatar_url to an already-published account.
    dedup: ClassVar[bool] = False

    IDENTICAL_THRESHOLD: ClassVar[int] = 4
    SIMILAR_THRESHOLD: ClassVar[int] = 10

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 10.0,
        concurrency: int = 4,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)
        # URLs we've already hashed (internal dedup — bypasses bus dedup)
        self._processed_urls: set[str] = set()
        # (account_id, phash_int, account) — for similarity search.
        # Linear scan is O(n) per new avatar; fine for <~1000 accounts.
        # For larger scale, swap in a BKTree for O(log n) nearest-neighbor.
        self._index: list[tuple[UUID, int, Account]] = []

    async def collect(self, event: EntityDiscovered) -> None:
        account = event.entity
        if not isinstance(account, Account):
            return
        avatar_url = getattr(account, "avatar_url", None)
        if not avatar_url:
            return
        if avatar_url in self._processed_urls:
            return
        self._processed_urls.add(avatar_url)

        async with self._semaphore:
            hash_result = await self._download_and_hash(avatar_url)
        if hash_result is None:
            return

        phash_int, sha256, width, height = hash_result

        # Emit ImageAsset — shared URLs naturally dedup via the store
        image = ImageAsset(
            value=avatar_url,
            sha256=sha256,
            perceptual_hash=f"{phash_int:016x}",
            width=width,
            height=height,
            evidence=[
                Evidence(
                    collector=self.name,
                    source_url=avatar_url,
                    confidence=0.95,
                    raw_data={"phash": f"{phash_int:016x}", "sha256": sha256},
                    notes=f"Perceptual hash computed ({width}x{height})",
                )
            ],
        )
        await self.emit(image, event)

        # Correlate against known avatars
        matches = 0
        for other_id, other_phash, other_account in self._index:
            if other_id == account.id:
                continue
            distance = self._hamming(phash_int, other_phash)
            if distance > self.SIMILAR_THRESHOLD:
                continue
            matches += 1
            confidence = self._confidence_from_distance(distance)
            label = "identical" if distance <= self.IDENTICAL_THRESHOLD else "similar"
            rel = Relationship(
                source_id=account.id,
                target_id=other_account.id,
                predicate="same_avatar_as",
                metadata={
                    "hamming_distance": distance,
                    "match_type": label,
                    "phash_a": f"{phash_int:016x}",
                    "phash_b": f"{other_phash:016x}",
                },
                evidence=[
                    Evidence(
                        collector=self.name,
                        confidence=confidence,
                        notes=(
                            f"pHash distance {distance} ({label}); "
                            f"{account.platform}:{account.username} ↔ "
                            f"{other_account.platform}:{other_account.username}"
                        ),
                    )
                ],
            )
            self.emit_relationship(rel)

        self._index.append((account.id, phash_int, account))
        if matches:
            self.log.info(
                "avatar of %s matched %d other account(s)",
                account.dedup_key(),
                matches,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _download_and_hash(
        self, url: str
    ) -> tuple[int, str, int, int] | None:
        """Fetch the image and return (phash_int, sha256, width, height).

        Returns None on any failure (network, bad image, missing deps).
        """
        try:
            import httpx
        except ImportError:
            self.log.error("httpx missing — cannot download avatars")
            return None
        try:
            import imagehash
            from PIL import Image
        except ImportError:
            self.log.error(
                "vision extras not installed. Run: pip install 'osint-core[vision]'"
            )
            return None

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                r = await client.get(
                    url,
                    headers={"User-Agent": "osint-core/0.1 (research)"},
                )
            if r.status_code != 200:
                self.log.debug("avatar fetch HTTP %d: %s", r.status_code, url)
                return None
            img_bytes = r.content
        except Exception as exc:
            self.log.debug("avatar fetch failed: %s (%s)", url, exc)
            return None

        try:
            sha = hashlib.sha256(img_bytes).hexdigest()
            # Pillow is strict about truncated files — convert to RGB to normalize
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            phash = imagehash.phash(img, hash_size=8)  # 64-bit hash
            phash_int = int(str(phash), 16)
            return phash_int, sha, img.width, img.height
        except Exception as exc:
            self.log.warning("failed to hash avatar %s: %s", url, exc)
            return None

    @staticmethod
    def _hamming(a: int, b: int) -> int:
        """Hamming distance between two 64-bit integers."""
        return (a ^ b).bit_count()  # Python 3.10+

    @classmethod
    def _confidence_from_distance(cls, d: int) -> float:
        """Map Hamming distance to a confidence score.

        d=0 → 0.98 (we stay below 1.0 since hash collisions exist)
        d=SIMILAR_THRESHOLD → ~0.50
        """
        frac = d / max(cls.SIMILAR_THRESHOLD, 1)
        return max(0.4, round(0.98 - 0.48 * frac, 3))
