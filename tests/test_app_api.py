"""Smoke test for the Poireaut GUI API.

We don't need pywebview to test the API class — it's a plain Python
object. We run a real (demo-mode) investigation through it and verify
the full lifecycle: start → poll → complete → graph + report written.
"""

import time
from pathlib import Path

from osint_core.app.api import InvestigationState, PoireautApi


def _wait_until_done(api: PoireautApi, inv_id: str, timeout: float = 10.0) -> dict:
    """Poll get_status until the investigation finishes or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = api.get_status(inv_id)
        if status.get("status") in ("done", "error"):
            return status
        time.sleep(0.05)
    raise TimeoutError(f"Investigation {inv_id} did not finish in {timeout}s")


def test_api_version_and_caps() -> None:
    api = PoireautApi()
    assert api.get_version()
    caps = api.get_capabilities()
    assert set(caps.keys()) == {"maigret", "vision", "holehe"}
    assert all(isinstance(v, bool) for v in caps.values())


def test_start_investigation_rejects_empty_target() -> None:
    api = PoireautApi()
    inv_id = api.start_investigation({"target": "   ", "target_type": "username"})
    status = api.get_status(inv_id)
    assert status["status"] == "error"
    assert status["error"] == "Cible vide"


def test_full_username_investigation_demo_mode() -> None:
    api = PoireautApi()
    inv_id = api.start_investigation(
        {
            "target": "alice",
            "target_type": "username",
            "maigret": False,     # demo mode
            "enrich": False,      # minimal flow — just the demo collector
            "holehe": False,
        }
    )
    final = _wait_until_done(api, inv_id)

    assert final["status"] == "done"
    assert final["target"] == "alice"
    assert final["target_type"] == "username"

    # Demo collector emits a seed Username + ~7 Accounts
    assert final["summary"].get("username") == 1
    assert final["summary"].get("account", 0) >= 5

    # The logs should include recognizable lifecycle markers
    logs_joined = "\n".join(final["logs"])
    assert "Début de l'enquête" in logs_joined
    assert "terminée" in logs_joined

    # Graph + report artifacts should be on disk
    assert final["graph_url"] and final["graph_url"].startswith("file://")
    assert Path(final["graph_url"].removeprefix("file://")).is_file()
    assert final["report_path"] and Path(final["report_path"]).is_file()


def test_get_status_unknown_id_is_not_found() -> None:
    api = PoireautApi()
    assert api.get_status("definitely-not-an-id") == {"error": "not_found"}


def test_email_seed_investigation_does_not_crash() -> None:
    """Seeding with an email should run cleanly — no username collectors fire
    (no --enrich, no --holehe) so it's essentially a no-op beyond recording."""
    api = PoireautApi()
    inv_id = api.start_investigation(
        {
            "target": "alice@example.com",
            "target_type": "email",
            "maigret": False,
            "enrich": False,
            "holehe": False,
        }
    )
    final = _wait_until_done(api, inv_id)
    assert final["status"] == "done"
    assert final["summary"].get("email") == 1
