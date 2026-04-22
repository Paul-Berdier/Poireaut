"""Demo collector — emits canned data to exercise the architecture.

Use this to validate the pipeline without installing Maigret. Replace with
real collectors as you build them out.
"""

from __future__ import annotations

import asyncio

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account


# Hand-picked plausible platforms for a demo investigation.
_DEMO_PLATFORMS: list[tuple[str, str, float]] = [
    ("github", "https://github.com/{u}", 0.90),
    ("gitlab", "https://gitlab.com/{u}", 0.85),
    ("reddit", "https://reddit.com/user/{u}", 0.80),
    ("keybase", "https://keybase.io/{u}", 0.90),
    ("dev.to", "https://dev.to/{u}", 0.80),
    ("medium", "https://medium.com/@{u}", 0.75),
    ("stackoverflow", "https://stackoverflow.com/users/{u}", 0.70),
]


class DemoUsernameCollector(BaseCollector):
    name = "demo_username"
    consumes = ["username"]
    produces = ["account"]

    async def collect(self, event: EntityDiscovered) -> None:
        username = event.entity.value
        self.log.info("demo collector scanning %s", username)

        # Simulate async I/O
        await asyncio.sleep(0.2)

        for platform, url_template, confidence in _DEMO_PLATFORMS:
            url = url_template.format(u=username)
            account = Account(
                value=f"{platform}:{username.lower()}",
                platform=platform,
                username=username,
                profile_url=url,
                evidence=[
                    Evidence(
                        collector=self.name,
                        source_url=url,
                        confidence=confidence,
                        notes="Demo data — NOT a real verification.",
                    )
                ],
            )
            await self.emit(account, event)
