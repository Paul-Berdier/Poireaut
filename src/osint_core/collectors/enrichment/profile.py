"""Profile enrichment collector.

Consumes Account entities, fetches their full profile data (via platform
API or generic HTML), runs all configured extractors against the bio,
and emits the discovered sub-entities back onto the bus.

It also upgrades the original Account with newly-learned fields
(display_name, avatar_url, bio, followers_count) by re-emitting it — the
store's merge() logic fills in the previously-None fields.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.collectors.enrichment.extractors import (
    DEFAULT_EXTRACTORS,
    Extractor,
)
from osint_core.collectors.enrichment.fetchers import FetchResult, ProfileFetcher
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account


class ProfileEnrichmentCollector(BaseCollector):
    name = "profile_enrichment"
    consumes: ClassVar[list[str]] = ["account"]
    produces: ClassVar[list[str]] = ["email", "url", "username", "location"]

    # By default, only enrich platforms we have a proper API fetcher for.
    # Opt into generic HTML enrichment at your own risk (rate limits, TOS).
    DEFAULT_ENABLED_PLATFORMS: ClassVar[frozenset[str]] = frozenset(
        {"github", "gitlab", "gravatar"}
    )

    def __init__(
        self,
        bus,
        fetcher: ProfileFetcher | None = None,
        extractors: list[Extractor] | None = None,
        enabled_platforms: frozenset[str] | set[str] | None = None,
        concurrency: int = 4,
    ) -> None:
        super().__init__(bus)
        self.fetcher = fetcher or ProfileFetcher()
        self.extractors = extractors if extractors is not None else list(DEFAULT_EXTRACTORS)
        self.enabled_platforms = frozenset(
            enabled_platforms
            if enabled_platforms is not None
            else self.DEFAULT_ENABLED_PLATFORMS
        )
        self._semaphore = asyncio.Semaphore(concurrency)

    async def collect(self, event: EntityDiscovered) -> None:
        account = event.entity
        if not isinstance(account, Account):
            self.log.debug("not an Account, skipping: %s", account)
            return

        platform = (account.platform or "").lower()
        if platform not in self.enabled_platforms:
            self.log.debug(
                "platform '%s' not enabled for enrichment (enabled=%s)",
                platform,
                sorted(self.enabled_platforms),
            )
            return

        async with self._semaphore:
            result = await self.fetcher.fetch(
                platform=platform,
                username=account.username or "",
                profile_url=account.profile_url or "",
            )

        if not result.ok:
            self.log.info(
                "enrichment returned no data for %s (status=%d)",
                account.dedup_key(),
                result.status,
            )
            return

        # 1) Upgrade the account with newly-learned fields (re-emit; store merges)
        await self._upgrade_account(account, result, event)

        # 2) Run extractors on the bio and emit each found entity
        await self._run_extractors(account, result, event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _upgrade_account(
        self,
        account: Account,
        result: FetchResult,
        origin: EntityDiscovered,
    ) -> None:
        """Re-publish the account with fields filled in from the fetch."""
        upgraded = Account(
            value=account.value,  # same dedup_key
            platform=account.platform,
            username=account.username,
            profile_url=account.profile_url,
            display_name=result.display_name,
            avatar_url=result.avatar_url,
            followers_count=result.followers,
            evidence=[
                Evidence(
                    collector=self.name,
                    source_url=result.fetched_url,
                    confidence=0.95,
                    notes="Account upgraded with fetched profile data.",
                    raw_data=result.extras,
                )
            ],
            metadata={"enriched": True, **result.extras},
        )
        await self.emit(upgraded, origin)

    async def _run_extractors(
        self,
        account: Account,
        result: FetchResult,
        origin: EntityDiscovered,
    ) -> None:
        context = {
            "profile_url": account.profile_url or "",
            "platform": account.platform,
            "username": account.username,
            "account_id": str(account.id),
        }
        emitted_count = 0
        for extractor in self.extractors:
            for entity, confidence in extractor.extract(result.bio, context):
                entity.evidence.append(
                    Evidence(
                        collector=self.name,
                        source_url=result.fetched_url,
                        confidence=confidence,
                        notes=(
                            f"extracted by {extractor.name} "
                            f"from {account.platform} bio of {account.username}"
                        ),
                        raw_data={
                            "extractor": extractor.name,
                            "source_account": account.value,
                        },
                    )
                )
                await self.emit(entity, origin)
                emitted_count += 1
        self.log.info(
            "enrichment of %s: emitted %d sub-entities",
            account.dedup_key(),
            emitted_count,
        )
