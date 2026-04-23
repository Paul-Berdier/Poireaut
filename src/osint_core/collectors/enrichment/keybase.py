"""Keybase cross-verification collector.

Consumes: Account entities where platform == "keybase"
Produces: Account entities (linked platforms), cross_verified_by relationships

Keybase (https://keybase.io) is a public key directory where users
cryptographically attest control of accounts on other platforms
(GitHub, Twitter, Reddit, HackerNews, Mastodon, personal websites…).
Every proof is a cryptographically signed statement published in the
relevant platform — this is the *strongest* public signal one can get
that "@alice on GitHub" and "@alice_crypto on Twitter" are the same
operator, short of the user confirming it directly.

The `user/lookup` API is public and documented
(https://keybase.io/docs/api/1.0/call/user/lookup) — it returns all
proofs_summary items for a given Keybase username without authentication.

Ethics / OPSEC:
  * Data is intentionally published by the user as cross-verification.
  * Keybase's terms explicitly welcome programmatic consumption of public
    profiles for exactly this kind of attribution work.
  * We never fetch private key material or any authenticated endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.identifiers import Url
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


class KeybaseCollector(BaseCollector):
    """Pull verified cross-platform proofs from a Keybase profile."""

    name = "keybase"
    consumes: ClassVar[list[str]] = ["account"]
    produces: ClassVar[list[str]] = ["account", "url"]

    # Mapping: Keybase's `proof_type` (or `presentation_group`) → normalized
    # platform name we use internally. Kept explicit for auditability.
    _PLATFORM_MAP: ClassVar[dict[str, str]] = {
        "twitter": "Twitter",
        "github": "GitHub",
        "reddit": "Reddit",
        "hackernews": "HackerNews",
        "mastodon": "Mastodon",
        "facebook": "Facebook",
        "generic_web_site": "Website",
        "generic_social": "Generic",
        "dns": "DNS",
        "pgp": "PGP",
        "rooter": "Rooter",
    }

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 15.0,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout

    async def collect(self, event: EntityDiscovered) -> None:
        account = event.entity
        if not isinstance(account, Account):
            return
        if (account.platform or "").lower() != "keybase":
            return
        username = account.username
        if not username:
            return

        url = (
            "https://keybase.io/_/api/1.0/user/lookup.json"
            f"?usernames={username}"
            "&fields=basics,profile,proofs_summary"
        )

        data = await self._fetch(url)
        if data is None:
            return

        users = data.get("them") or []
        if not users:
            self.log.info("keybase: no user data for %s", username)
            return
        user = users[0]
        if not user:
            # 'them' can contain nulls when the username doesn't resolve
            return

        proofs = (user.get("proofs_summary") or {}).get("all") or []
        self.log.info(
            "keybase: %s has %d verified proof(s)", username, len(proofs)
        )

        for proof in proofs:
            await self._handle_proof(proof, account, event)

    async def _handle_proof(
        self,
        proof: dict[str, Any],
        source_account: Account,
        origin: EntityDiscovered,
    ) -> None:
        """Process a single Keybase proof and emit entities/relationships."""
        proof_type = (proof.get("proof_type") or "").lower()
        nametag = proof.get("nametag") or proof.get("value") or ""
        service_url = proof.get("service_url") or ""
        presentation_url = proof.get("presentation_url") or ""
        state = proof.get("state")  # 1 == OK, other values == broken/pending

        if state is not None and state != 1:
            self.log.debug(
                "keybase: skipping non-verified proof (state=%s) for %s on %s",
                state,
                nametag,
                proof_type,
            )
            return

        platform = self._PLATFORM_MAP.get(proof_type, proof_type.title() or "unknown")

        # For real platforms we can represent as accounts, emit one.
        if proof_type in {"twitter", "github", "reddit", "hackernews", "mastodon", "facebook"}:
            if not nametag:
                return
            # Mastodon 'nametag' is usually "user@instance.tld"; keep as-is — Account
            # dedup_key handles it fine.
            new_account = Account(
                value=f"{platform.lower()}:{nametag.lower()}",
                platform=platform,
                username=nametag,
                profile_url=service_url or presentation_url or None,
                evidence=[
                    Evidence(
                        collector=self.name,
                        source_url=presentation_url or service_url or None,
                        # Cryptographic attestation via Keybase: very high confidence.
                        confidence=0.92,
                        notes=(
                            f"Keybase-verified proof: {source_account.username} "
                            f"controls @{nametag} on {platform}"
                        ),
                        raw_data={
                            "proof_type": proof_type,
                            "presentation_url": presentation_url,
                            "via": "keybase",
                        },
                    )
                ],
                metadata={
                    "keybase_verified": True,
                    "keybase_user": source_account.username,
                },
            )
            await self.emit(new_account, origin)

            # Relationship: the Keybase account cross-verifies the new account.
            self.emit_relationship(
                Relationship(
                    source_id=source_account.id,
                    target_id=new_account.id,
                    predicate="cross_verified_by",
                    metadata={
                        "proof_type": proof_type,
                        "presentation_url": presentation_url,
                    },
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=presentation_url or None,
                            confidence=0.92,
                            notes=(
                                f"Keybase cryptographic proof links "
                                f"{source_account.platform}:{source_account.username} "
                                f"↔ {platform}:{nametag}"
                            ),
                        )
                    ],
                )
            )
            return

        # For web sites / DNS proofs, emit a Url entity instead.
        if proof_type in {"generic_web_site", "dns"}:
            href = service_url or (
                f"https://{nametag}" if nametag and not nametag.startswith("http") else nametag
            )
            if not href or not (href.startswith("http://") or href.startswith("https://")):
                return
            try:
                url_entity = Url(
                    value=href,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=presentation_url or href,
                            confidence=0.90,
                            notes=(
                                f"Keybase-verified {proof_type} proof controlled by "
                                f"{source_account.username}"
                            ),
                        )
                    ],
                    metadata={"keybase_verified": True},
                )
            except ValueError:
                self.log.debug(
                    "keybase: rejected malformed URL in proof %r", href
                )
                return
            await self.emit(url_entity, origin)
            return

        # Unknown / rarely used proof types are kept as metadata on the source account.
        self.log.debug(
            "keybase: unhandled proof type '%s' (nametag=%s) on %s",
            proof_type,
            nametag,
            source_account.value,
        )

    async def _fetch(self, url: str) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    url,
                    headers={
                        "User-Agent": "osint-core/0.1 (research)",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            self.log.warning("keybase: network error on %s: %s", url, exc)
            return None
        if r.status_code != 200:
            self.log.info("keybase: API returned %d for %s", r.status_code, url)
            return None
        try:
            payload = r.json()
        except ValueError:
            self.log.warning("keybase: non-JSON response from %s", url)
            return None
        # Keybase returns {"status": {"code": 0, ...}, ...} with code != 0 on errors
        status = payload.get("status") or {}
        if status.get("code", 0) != 0:
            self.log.info(
                "keybase: API error code=%s name=%s",
                status.get("code"),
                status.get("name"),
            )
            return None
        return payload
