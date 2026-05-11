"""Periodic Maigret site health probe.

Each site bundled with Maigret has a URL template like:
    "https://example.com/users/{username}"

We probe each site with a known-impossible username (40-char random
string) and classify the response:

  - DEAD: HTTP error (timeout, DNS, connection refused)
  - BLOCKING: 403 / 999 / Cloudflare challenge
  - FALSE_POSITIVE: 200 + content "user found" pattern. The site can't
    distinguish a real user from a fake one — every Maigret hit on it
    is unreliable.
  - OK: 404 or a 200 with a "not found" pattern (expected behaviour)

Disabled sites are written back to maigret_site_health.is_disabled=True.
The Maigret connector reads this table at runtime via `_load_blacklist`
and passes the disabled site names as Maigret's `disabled_sites_set`.

The task is idempotent and concurrency-safe: each site is upserted
individually, so a Beat retry mid-run doesn't double-count anything.
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.maigret_site_health import MaigretSiteHealth

logger = logging.getLogger(__name__)

# A long random string we use as the test "username" — guaranteed to not
# exist on any real platform. We don't want false-positive matches.
def _generate_test_username() -> str:
    return "poireaut_probe_" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=24)
    )


# How many sites to probe in parallel. Lower = slower, more polite.
PROBE_CONCURRENCY = 20
PROBE_TIMEOUT = 12   # per-site HTTP timeout in seconds


# Patterns suggesting the response page says the user does NOT exist —
# means the site correctly distinguishes between real/fake users.
_NOT_FOUND_PATTERNS = (
    "not found", "doesn't exist", "does not exist",
    "no such user", "user not found", "page not found",
    "n'existe pas", "introuvable", "compte introuvable",
    "404", "not_found",
)


async def probe_one_site(
    client: httpx.AsyncClient,
    site_name: str,
    url_template: str,
    test_username: str,
) -> tuple[str, str, int | None, str | None]:
    """Probe a single Maigret site.

    Returns (status, classification_reason, http_status, error_message).
    Status is one of: ok / dead / blocking / false_positive.
    """
    try:
        url = url_template.replace("{username}", test_username)
    except Exception as exc:  # noqa: BLE001
        return "dead", f"template error: {exc}", None, str(exc)

    try:
        resp = await client.get(
            url,
            timeout=PROBE_TIMEOUT,
            follow_redirects=True,
            headers={
                "user-agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
    except httpx.HTTPError as exc:
        return "dead", f"HTTP error: {type(exc).__name__}", None, str(exc)[:200]
    except Exception as exc:  # noqa: BLE001
        return "dead", f"unexpected: {type(exc).__name__}", None, str(exc)[:200]

    status_code = resp.status_code

    if status_code in (403, 401, 999):
        return "blocking", f"HTTP {status_code}", status_code, None

    if status_code in (404, 410):
        # Expected behaviour: site correctly says "user not found"
        return "ok", f"HTTP {status_code}", status_code, None

    if status_code >= 500:
        return "dead", f"HTTP {status_code}", status_code, None

    if status_code in (200, 201):
        # 200 OK on a guaranteed-fake username is suspicious. Check the body
        # for "not found" hints — if present, the site is OK (it returns
        # a "user not found" *page* with HTTP 200). Otherwise it's a false
        # positive: the site responds OK to every request.
        body = (resp.text or "")[:8000].lower()
        if any(pat in body for pat in _NOT_FOUND_PATTERNS):
            return "ok", "200 with not-found page", status_code, None
        return "false_positive", "200 OK on fake user", status_code, None

    # Anything else (3xx with no follow, etc.) — flag as questionable
    return "dead", f"HTTP {status_code}", status_code, None


async def refresh_maigret_site_health_async(
    session_maker, batch_size: int = 0,
) -> dict[str, Any]:
    """Run a full pass over Maigret's bundled site DB.

    `session_maker` is a callable returning an AsyncSession (we accept a
    callable rather than the session itself so the function can recycle
    transactions across the long probe run).

    `batch_size`: optional cap on how many sites to probe (0 = all).
    Useful for smoke-testing in dev.
    """
    try:
        import maigret as maigret_pkg
        from maigret.sites import MaigretDatabase
    except ImportError as exc:
        return {"error": f"Maigret not available: {exc}"}

    import os
    try:
        db_path = os.path.join(
            maigret_pkg.__path__[0], "resources", "data.json",
        )
        site_db = MaigretDatabase().load_from_file(db_path)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to load Maigret site DB: {exc}"}

    site_dict = site_db.sites_dict
    sites = list(site_dict.items())
    if batch_size > 0:
        sites = sites[:batch_size]

    test_user = _generate_test_username()

    classifications: dict[str, int] = {}
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def _probe_and_persist(client, name: str, info):
        async with semaphore:
            url_tpl = getattr(info, "url", None) or getattr(info, "urlMain", None)
            if not url_tpl or "{username}" not in url_tpl:
                # Sites without a templatable URL (rare); skip with status
                # "unknown" — Maigret's own scan logic handles them.
                return name, "unknown", "no url template", None, None

            status, reason, http_status, err = await probe_one_site(
                client, name, url_tpl, test_user,
            )
            return name, status, reason, http_status, err

    async with httpx.AsyncClient() as client:
        tasks = [_probe_and_persist(client, n, s) for n, s in sites]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Persist in chunks so we don't hold a single transaction for ~2 minutes.
    CHUNK = 100
    for offset in range(0, len(results), CHUNK):
        chunk = results[offset:offset + CHUNK]
        async with session_maker() as db:
            for item in chunk:
                if isinstance(item, BaseException):
                    logger.warning("probe task crashed: %s", item)
                    continue
                site_name, status, reason, http_status, err = item
                classifications[status] = classifications.get(status, 0) + 1
                await _upsert_site_health(db, site_name, status, http_status, err)
            await db.commit()

    return {
        "probed": len(results),
        "classifications": classifications,
    }


async def _upsert_site_health(
    db: AsyncSession,
    site_name: str,
    status: str,
    http_status: int | None,
    error: str | None,
) -> None:
    stmt = select(MaigretSiteHealth).where(MaigretSiteHealth.site_name == site_name)
    row = (await db.execute(stmt)).scalar_one_or_none()

    is_disabled = status in {"dead", "false_positive", "blocking"}

    if row is None:
        row = MaigretSiteHealth(
            site_name=site_name,
            status=status,
            is_disabled=is_disabled,
            last_checked_at=datetime.now(timezone.utc),
            last_http_status=http_status,
            last_error=error,
            consecutive_failures=(1 if is_disabled else 0),
            consecutive_successes=(0 if is_disabled else 1),
        )
        db.add(row)
        return

    row.status = status
    row.is_disabled = is_disabled
    row.last_checked_at = datetime.now(timezone.utc)
    row.last_http_status = http_status
    row.last_error = error
    if is_disabled:
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.consecutive_successes = 0
    else:
        row.consecutive_successes = (row.consecutive_successes or 0) + 1
        row.consecutive_failures = 0


async def load_disabled_sites(db: AsyncSession) -> set[str]:
    """Read the current Maigret blacklist from DB.

    Returns the set of site names Maigret should skip. Used by the
    maigret connector at runtime.
    """
    stmt = select(MaigretSiteHealth.site_name).where(
        MaigretSiteHealth.is_disabled.is_(True),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return set(rows)
