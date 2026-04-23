"""Tests for the Poireaut API with multi-seed dossier format."""

import time
from pathlib import Path
from osint_core.app.api import PoireautApi


def _wait(api, inv_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = api.get_status(inv_id)
        if st.get("status") in ("done", "error"):
            return st
        time.sleep(0.05)
    raise TimeoutError(f"timeout on {inv_id}")


def test_version_and_caps():
    api = PoireautApi()
    assert api.get_version()
    caps = api.get_capabilities()
    assert "maigret" in caps and "vision" in caps and "holehe" in caps


def test_empty_seeds_rejected():
    api = PoireautApi()
    inv_id = api.start_investigation({"seeds": []})
    st = api.get_status(inv_id)
    assert st["status"] == "error"


def test_username_investigation():
    api = PoireautApi()
    inv_id = api.start_investigation({
        "seeds": [{"value": "alice", "type": "username"}]
    })
    st = _wait(api, inv_id)
    assert st["status"] == "done"
    assert st["summary"].get("username", 0) >= 1
    assert Path(st["report_path"]).is_file()


def test_email_investigation():
    api = PoireautApi()
    inv_id = api.start_investigation({
        "seeds": [{"value": "test@example.com", "type": "email"}]
    })
    st = _wait(api, inv_id)
    assert st["status"] == "done"
    assert st["summary"].get("email", 0) >= 1


def test_multi_seed():
    api = PoireautApi()
    inv_id = api.start_investigation({
        "seeds": [
            {"value": "alice", "type": "username"},
            {"value": "test@example.com", "type": "email"},
        ]
    })
    st = _wait(api, inv_id)
    assert st["status"] == "done"
    assert st["summary"].get("username", 0) >= 1
    assert st["summary"].get("email", 0) >= 1


def test_unknown_id():
    api = PoireautApi()
    assert api.get_status("nope") == {"error": "not_found"}
