"""GitHub public commits / events collector.

Consumes: Account entities where platform == "github"
Produces: Email entities, co_authored_with relationships

When a user pushes commits to a public repository, the commit metadata —
which includes the author email and co-author emails — becomes part of the
permanent public Git history. GitHub exposes this via the Events API:

    GET https://api.github.com/users/{username}/events/public

This returns the user's 30 most recent public events. For PushEvents, each
commit carries an `author.email` field. Very often the user's real personal
email (first.last@gmail.com) leaks here even though their GitHub profile
shows only a `@users.noreply.github.com` masked address.

This collector is read-only and uses the documented public REST endpoint.
It honors rate limits (60 req/h unauthenticated; 5000 req/h with a PAT via
GITHUB_TOKEN). Results are emitted as Email entities and the link is
preserved in the graph via a `commits_as` Relationship.

Ethics / OPSEC:
  * Data is already public — we only aggregate what the user chose to push.
  * We skip GitHub's `@users.noreply.github.com` masked addresses — they
    contribute no new attribution signal.
  * We cap per-account processing at RECENT_EVENT_LIMIT to avoid hammering.
"""

from __future__ import annotations

import logging
import os
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.identifiers import Email
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


class GitHubCommitsCollector(BaseCollector):
    """Extract committer emails from a GitHub user's public events."""

    name = "github_commits"
    consumes: ClassVar[list[str]] = ["account"]
    produces: ClassVar[list[str]] = ["email"]

    # GitHub returns up to 30 events per page; we look at one page by default.
    RECENT_EVENT_LIMIT: ClassVar[int] = 30
    # Skip GitHub-synthesized masked addresses — they add no attribution signal.
    _NOREPLY_SUFFIX = "@users.noreply.github.com"

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
        if (account.platform or "").lower() != "github":
            return
        username = account.username
        if not username:
            return

        url = f"https://api.github.com/users/{username}/events/public"
        headers = {
            "User-Agent": "osint-core/0.1 (research)",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        events = await self._fetch_events(url, headers)
        if events is None:
            return

        # Map: email -> (count, sample_commit_url)
        emails: dict[str, tuple[int, str]] = {}
        for ev in events[: self.RECENT_EVENT_LIMIT]:
            if ev.get("type") != "PushEvent":
                continue
            repo_name = (ev.get("repo") or {}).get("name", "")
            payload = ev.get("payload") or {}
            for commit in payload.get("commits") or []:
                author = commit.get("author") or {}
                email = (author.get("email") or "").strip().lower()
                if not email or email.endswith(self._NOREPLY_SUFFIX):
                    continue
                sha = commit.get("sha", "")
                commit_url = (
                    f"https://github.com/{repo_name}/commit/{sha}" if repo_name and sha else ""
                )
                count, existing_url = emails.get(email, (0, ""))
                emails[email] = (count + 1, existing_url or commit_url)

        if not emails:
            self.log.info(
                "github_commits: no non-noreply emails found in %s's recent events",
                username,
            )
            return

        self.log.info(
            "github_commits: %d distinct email(s) in %s's recent commits",
            len(emails),
            username,
        )

        for email_value, (count, commit_url) in emails.items():
            try:
                email_entity = Email(
                    value=email_value,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=commit_url or url,
                            # Confidence scales with repeated observations but tops
                            # out below "confirmed" — a committer email isn't proof
                            # the account *owner* controls that mailbox (could be
                            # a work address, a team box, a placeholder…).
                            confidence=min(0.60 + 0.05 * (count - 1), 0.85),
                            notes=(
                                f"Observed in {count} public commit(s) "
                                f"authored by @{username} on GitHub"
                            ),
                            raw_data={
                                "commits_observed": count,
                                "github_user": username,
                            },
                        )
                    ],
                    metadata={"source_account": account.value},
                )
            except ValueError:
                self.log.debug(
                    "github_commits: rejected malformed email %r", email_value
                )
                continue

            await self.emit(email_entity, event)

            # Explicit edge Account --commits_as--> Email
            self.emit_relationship(
                Relationship(
                    source_id=account.id,
                    target_id=email_entity.id,
                    predicate="commits_as",
                    metadata={"commits_observed": count},
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=commit_url or url,
                            confidence=0.85,
                            notes=f"{count} commit(s) in public GitHub events",
                        )
                    ],
                )
            )

    async def _fetch_events(
        self, url: str, headers: dict[str, str]
    ) -> list[dict[str, Any]] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            self.log.warning("github_commits: network error on %s: %s", url, exc)
            return None

        if r.status_code == 404:
            # User has no public events, or username mismatch; not an error.
            return []
        if r.status_code == 403:
            # Rate-limited. Surface once as a warning; don't kill the pipeline.
            self.log.warning(
                "github_commits: GitHub API rate-limited (403). "
                "Set GITHUB_TOKEN for a higher quota."
            )
            return None
        if r.status_code != 200:
            self.log.info(
                "github_commits: GitHub API returned %d for %s", r.status_code, url
            )
            return None
        try:
            data = r.json()
        except ValueError:
            self.log.warning("github_commits: non-JSON response from %s", url)
            return None
        if not isinstance(data, list):
            return None
        return data
