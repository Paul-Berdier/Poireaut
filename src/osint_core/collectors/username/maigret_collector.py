"""Maigret-powered username enumeration via subprocess.

Calls the `maigret` CLI rather than importing unstable internal APIs.
This works reliably across all maigret versions as long as the package
is installed and the CLI is on PATH.

Flow:
  1. Run `maigret <username> --json <tmpfile> --no-color --timeout <N>`
  2. Parse the JSON output
  3. Emit Account entities for each confirmed profile
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


def is_maigret_available() -> str | None:
    """Return path to maigret executable, or None if not found.

    Checks: 1) system PATH, 2) current venv Scripts dir, 3) python -m maigret.
    """
    import sys

    # 1. On PATH
    found = shutil.which("maigret")
    if found:
        return found

    # 2. In the current venv's Scripts (Windows) or bin (Unix)
    venv_dir = Path(sys.executable).parent
    for name in ("maigret.exe", "maigret"):
        candidate = venv_dir / name
        if candidate.is_file():
            return str(candidate)

    # 3. Try as python module
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "maigret", "--version"],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            return f"{sys.executable} -m maigret"
    except Exception:
        pass

    return None


class MaigretCollector(BaseCollector):
    """Username enumeration via Maigret CLI (3000+ sites)."""

    name = "maigret"
    consumes: ClassVar[list[str]] = ["username"]
    produces: ClassVar[list[str]] = ["account"]

    def __init__(self, bus, relationship_sink=None, top_sites: int = 500, timeout: int = 30) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.top_sites = top_sites
        self.timeout = timeout

    async def collect(self, event: EntityDiscovered) -> None:
        username = event.entity.value

        maigret_path = is_maigret_available()
        if not maigret_path:
            self.log.error("maigret not found (neither on PATH nor in venv)")
            return

        self.log.info(
            "maigret: scanning '%s' (top %d sites, timeout %ds)...",
            username, self.top_sites, self.timeout,
        )

        results = await self._run_maigret(username, maigret_path)
        if results is None:
            return

        found_count = 0
        for entry in results:
            site_name = entry.get("sitename") or entry.get("site", {}).get("name", "unknown")
            url = entry.get("url") or entry.get("link", "")
            status = str(entry.get("status", "")).lower()

            if "claimed" not in status and status != "found":
                continue

            found_count += 1
            ids = entry.get("ids", {}) or {}

            account = Account(
                value=f"{site_name.lower()}:{username.lower()}",
                platform=site_name,
                username=username,
                profile_url=url,
                display_name=ids.get("fullname") or ids.get("name"),
                bio=ids.get("bio") or ids.get("description"),
                avatar_url=ids.get("image") or ids.get("avatar"),
                evidence=[
                    Evidence(
                        collector=self.name,
                        source_url=url,
                        confidence=0.90,
                        notes=f"Maigret confirmed profile on {site_name}",
                        raw_data={"site": site_name, "ids": ids},
                    )
                ],
            )
            await self.emit(account, event)

        self.log.info("maigret: '%s' found on %d sites", username, found_count)

    async def _run_maigret(self, username: str, maigret_path: str) -> list[dict[str, Any]] | None:
        """Run maigret as a subprocess and parse JSON output."""
        import sys

        with tempfile.TemporaryDirectory(prefix="maigret-") as tmpdir:
            json_path = Path(tmpdir) / "results.json"

            # Handle "python -m maigret" format
            if "-m maigret" in maigret_path:
                cmd = [
                    sys.executable, "-m", "maigret", username,
                    "--json", str(json_path),
                    "--no-color",
                    "--timeout", str(self.timeout),
                    "--top-sites", str(self.top_sites),
                ]
            else:
                cmd = [
                    maigret_path, username,
                    "--json", str(json_path),
                    "--no-color",
                    "--timeout", str(self.timeout),
                    "--top-sites", str(self.top_sites),
                ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout * 2 + 60,  # generous timeout
                )
            except asyncio.TimeoutError:
                self.log.warning("maigret subprocess timed out for '%s'", username)
                return None
            except FileNotFoundError:
                self.log.error("maigret CLI not found")
                return None
            except Exception as exc:
                self.log.error("maigret subprocess error: %s", exc)
                return None

            if not json_path.exists():
                # Some maigret versions output to a different filename
                # Try to find any .json in the tmpdir
                jsons = list(Path(tmpdir).glob("*.json"))
                if jsons:
                    json_path = jsons[0]
                else:
                    # Try parsing stdout as JSON
                    try:
                        return json.loads(stdout.decode("utf-8", errors="replace"))
                    except Exception:
                        self.log.warning("maigret produced no JSON output")
                        return None

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    # Some versions wrap results under a key
                    for key in ("results", "data", username):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                    # Flat dict: {site_name: {url, status, ...}}
                    return [{"sitename": k, **v} for k, v in data.items() if isinstance(v, dict)]
                return None
            except Exception as exc:
                self.log.warning("failed to parse maigret JSON: %s", exc)
                return None
