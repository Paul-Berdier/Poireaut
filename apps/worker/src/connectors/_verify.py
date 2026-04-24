"""Shared HTTP verification helpers used by multiple connectors.

After Holehe/Maigret say "this account probably exists", we can go one step
further: actually HEAD or GET the public profile URL and see what comes back.
That gives us:
  - A real HTTP status (200 vs 404) — the most reliable signal
  - An optional content check (does the page mention the username?)
  - A confidence score that's grounded in observable behavior

This module stays deliberately simple — no async frameworks like playwright,
just httpx with a realistic user-agent and a short timeout. Sites that block
crawlers will show up as `uncertain` rather than `confirmed`; the caller
decides how to weight that.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 6.0
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


Verdict = Literal["confirmed", "uncertain", "missing", "unreachable"]


@dataclass
class VerifyResult:
    verdict: Verdict
    status_code: int | None
    final_url: str | None
    confidence: float
    reason: str


async def verify_url(
    url: str,
    *,
    mention: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> VerifyResult:
    """Verify a profile URL is live and (optionally) mentions a username.

    Uses GET so we can peek at the body. We cap the body to 64 KB.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"user-agent": DEFAULT_UA, "accept-language": "en-US,en;q=0.5"},
            follow_redirects=True,
        )
    try:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            return VerifyResult(
                verdict="unreachable",
                status_code=None,
                final_url=None,
                confidence=0.3,
                reason=f"Network error: {type(exc).__name__}",
            )

        code = resp.status_code
        final = str(resp.url)

        if code == 404 or code == 410:
            return VerifyResult(
                verdict="missing",
                status_code=code,
                final_url=final,
                confidence=0.1,
                reason=f"HTTP {code} — profile seems gone",
            )
        if code >= 400:
            return VerifyResult(
                verdict="uncertain",
                status_code=code,
                final_url=final,
                confidence=0.35,
                reason=f"HTTP {code}",
            )

        # 200 / 2xx / 3xx that redirected successfully
        body = resp.text[:65_536] if resp.content else ""
        if mention and body:
            if mention.lower() in body.lower():
                return VerifyResult(
                    verdict="confirmed",
                    status_code=code,
                    final_url=final,
                    confidence=0.95,
                    reason=f"HTTP {code} and page mentions “{mention}”",
                )
            # 200 but no mention — could be a "username available" page.
            # Heuristic: some sites return a generic page that says "not found".
            lowered = body.lower()
            negative_hints = (
                "user not found", "account not found", "page not found",
                "sorry, that page",  "doesn't exist",  "does not exist",
                "aucun utilisateur", "introuvable", "cette page n'existe pas",
            )
            if any(hint in lowered for hint in negative_hints):
                return VerifyResult(
                    verdict="missing",
                    status_code=code,
                    final_url=final,
                    confidence=0.2,
                    reason=f"HTTP {code} but body says profile missing",
                )
            return VerifyResult(
                verdict="uncertain",
                status_code=code,
                final_url=final,
                confidence=0.55,
                reason=f"HTTP {code} but username not found in page",
            )

        return VerifyResult(
            verdict="confirmed",
            status_code=code,
            final_url=final,
            confidence=0.85,
            reason=f"HTTP {code}",
        )
    finally:
        if owns_client:
            await client.aclose()


async def verify_many(
    urls_and_mentions: list[tuple[str, str | None]],
    *,
    concurrency: int = 12,
) -> dict[str, VerifyResult]:
    """Verify many URLs in parallel, bounded by `concurrency`.

    Returns {url: VerifyResult}. Failures are captured as `unreachable`,
    never raised — so the caller doesn't need try/except around it.
    """
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        headers={"user-agent": DEFAULT_UA, "accept-language": "en-US,en;q=0.5"},
        follow_redirects=True,
    ) as client:
        async def _one(pair: tuple[str, str | None]) -> tuple[str, VerifyResult]:
            url, mention = pair
            async with sem:
                try:
                    r = await verify_url(url, mention=mention, client=client)
                except Exception as exc:  # noqa: BLE001
                    r = VerifyResult(
                        verdict="unreachable",
                        status_code=None,
                        final_url=None,
                        confidence=0.2,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                return url, r

        results = await asyncio.gather(*(_one(p) for p in urls_and_mentions))
    return dict(results)
