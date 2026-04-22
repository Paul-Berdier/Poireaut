"""Gravatar lookup — email → Gravatar account if one exists.

Gravatar is a globally-recognized avatar service: any email address may
have an associated profile at `gravatar.com/<md5-of-email>`. Because the
MD5 is public, anyone with an email can check if a Gravatar exists.

We emit the Gravatar presence as an `Account(platform="gravatar")` with
the avatar URL pre-filled. Downstream:

  * ProfileEnrichmentCollector fetches the Gravatar profile JSON and
    extracts the bio, linked URLs, and cross-referenced platform
    accounts — a gold mine of attribution data.
  * AvatarHashCollector hashes the avatar, enabling `same_avatar_as`
    correlations with other accounts sharing that image.

Privacy note: we only hash the email with MD5 locally and query a public
CDN endpoint. No copy of the email is sent to Gravatar.
"""

from __future__ import annotations

import hashlib
from typing import ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email
from osint_core.entities.profiles import Account


GRAVATAR_SIZE = 256


class GravatarCollector(BaseCollector):
    name = "gravatar"
    consumes: ClassVar[list[str]] = ["email"]
    produces: ClassVar[list[str]] = ["account"]

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 8.0,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout

    async def collect(self, event: EntityDiscovered) -> None:
        email = event.entity
        if not isinstance(email, Email):
            return

        md5_hash = hashlib.md5(
            email.value.strip().lower().encode("utf-8")
        ).hexdigest()
        avatar_url = (
            f"https://www.gravatar.com/avatar/{md5_hash}?d=404&s={GRAVATAR_SIZE}"
        )
        profile_url = f"https://www.gravatar.com/{md5_hash}"

        exists = await self._gravatar_exists(avatar_url)
        if not exists:
            self.log.debug("no Gravatar for %s", email.value)
            return

        account = Account(
            value=f"gravatar:{md5_hash}",
            platform="gravatar",
            username=md5_hash,
            profile_url=profile_url,
            avatar_url=avatar_url,
            evidence=[
                Evidence(
                    collector=self.name,
                    source_url=profile_url,
                    confidence=0.95,
                    notes=f"Gravatar exists for {email.value}",
                    raw_data={"email_md5": md5_hash, "email": email.value},
                )
            ],
        )
        await self.emit(account, event)

    async def _gravatar_exists(self, avatar_url: str) -> bool:
        """HEAD request with ?d=404 — returns 200 if an avatar is registered,
        404 if Gravatar has nothing for this hash."""
        try:
            import httpx
        except ImportError:
            self.log.error("httpx missing — cannot check Gravatar")
            return False
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=False
            ) as client:
                r = await client.head(
                    avatar_url,
                    headers={"User-Agent": "osint-core/0.1 (research)"},
                )
        except Exception as exc:
            self.log.debug("Gravatar HEAD failed: %s", exc)
            return False
        return r.status_code == 200
