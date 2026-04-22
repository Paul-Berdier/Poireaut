"""JS bridge API exposed to the Poireaut webview frontend.

The frontend calls these methods via `window.pywebview.api.<method>(args)`,
which returns a Promise. We run actual investigations in background
threads so the UI stays responsive.

Thread model
------------
Each `start_investigation` spins up a dedicated thread that calls
`asyncio.run()` on the async pipeline. Progress and log lines are pushed
into a shared dict protected by a lock. The UI polls `get_status(inv_id)`
to stream updates — simple and robust.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from osint_core import __version__
from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.email import (
    EmailDomainExtractor,
    GravatarCollector,
    HoleheCollector,
)
from osint_core.collectors.enrichment.profile import ProfileEnrichmentCollector
from osint_core.collectors.username.demo_collector import DemoUsernameCollector
from osint_core.collectors.username.maigret_collector import MaigretCollector
from osint_core.collectors.vision.avatar_hash import AvatarHashCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email, Username
from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization import render_html

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Investigation state
# ---------------------------------------------------------------------------


@dataclass
class InvestigationState:
    id: str
    target: str
    target_type: str              # "username" | "email"
    status: str = "pending"       # pending | running | done | error
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    summary: dict[str, int] = field(default_factory=dict)
    graph_html_path: str | None = None
    report_json_path: str | None = None
    error: str | None = None
    cancelled: bool = False


# ---------------------------------------------------------------------------
# Logging handler that writes into an InvestigationState.logs
# ---------------------------------------------------------------------------


class _StateLogHandler(logging.Handler):
    def __init__(self, state: InvestigationState) -> None:
        super().__init__(level=logging.INFO)
        self.state = state
        self.setFormatter(
            logging.Formatter("%(asctime)s · %(name)s · %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.state.logs.append(self.format(record))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Capability probe — what extras are installed
# ---------------------------------------------------------------------------


def _probe_capabilities() -> dict[str, bool]:
    caps = {"maigret": False, "vision": False, "holehe": False}
    try:
        import maigret  # noqa: F401
        caps["maigret"] = True
    except ImportError:
        pass
    try:
        import imagehash  # noqa: F401
        import PIL  # noqa: F401
        caps["vision"] = True
    except ImportError:
        pass
    try:
        import holehe  # noqa: F401
        caps["holehe"] = True
    except ImportError:
        pass
    return caps


# ---------------------------------------------------------------------------
# The JS-facing API
# ---------------------------------------------------------------------------


class PoireautApi:
    def __init__(self) -> None:
        self._investigations: dict[str, InvestigationState] = {}
        self._lock = threading.Lock()
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="poireaut-"))

    # ------------------------------------------------------------------
    # Meta endpoints
    # ------------------------------------------------------------------

    def get_version(self) -> str:
        return __version__

    def get_capabilities(self) -> dict[str, bool]:
        return _probe_capabilities()

    # ------------------------------------------------------------------
    # Investigation lifecycle
    # ------------------------------------------------------------------

    def start_investigation(self, config: dict[str, Any]) -> str:
        """Kick off an investigation in a background thread.

        `config` keys:
          - target: str (required)
          - target_type: "username" | "email"
          - maigret: bool
          - enrich: bool
          - holehe: bool
          - maigret_top: int (optional, default 500)
        """
        inv_id = uuid.uuid4().hex[:12]
        state = InvestigationState(
            id=inv_id,
            target=config.get("target", "").strip(),
            target_type=config.get("target_type", "username"),
        )
        if not state.target:
            state.status = "error"
            state.error = "Cible vide"
            with self._lock:
                self._investigations[inv_id] = state
            return inv_id

        with self._lock:
            self._investigations[inv_id] = state

        thread = threading.Thread(
            target=self._run_in_thread,
            args=(state, config),
            daemon=True,
            name=f"poireaut-inv-{inv_id}",
        )
        thread.start()
        return inv_id

    def get_status(self, inv_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._investigations.get(inv_id)
        if state is None:
            return {"error": "not_found"}
        return {
            "id": state.id,
            "target": state.target,
            "target_type": state.target_type,
            "status": state.status,
            "logs": list(state.logs),
            "summary": state.summary,
            "graph_url": f"file://{state.graph_html_path}" if state.graph_html_path else None,
            "report_path": state.report_json_path,
            "error": state.error,
        }

    def cancel_investigation(self, inv_id: str) -> bool:
        with self._lock:
            state = self._investigations.get(inv_id)
        if state is None or state.status in ("done", "error"):
            return False
        state.cancelled = True  # best effort — the thread will notice when it can
        return True

    def save_report(self, inv_id: str, path: str) -> dict[str, Any]:
        with self._lock:
            state = self._investigations.get(inv_id)
        if state is None or not state.report_json_path:
            return {"ok": False, "error": "No report available"}
        try:
            dest = Path(path)
            dest.write_bytes(Path(state.report_json_path).read_bytes())
            return {"ok": True, "path": str(dest)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internals: the actual pipeline
    # ------------------------------------------------------------------

    def _run_in_thread(
        self, state: InvestigationState, config: dict[str, Any]
    ) -> None:
        handler = _StateLogHandler(state)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        try:
            state.status = "running"
            state.logs.append("🔎  Début de l'enquête")
            asyncio.run(self._async_run(state, config))
            if state.cancelled:
                state.status = "error"
                state.error = "Cancelled"
                state.logs.append("⏹  Enquête interrompue")
            else:
                state.status = "done"
                state.logs.append(f"✓  Enquête terminée — {sum(v for k, v in state.summary.items() if k != 'relationships')} entités")
        except Exception as exc:
            log.exception("Investigation crashed")
            state.status = "error"
            state.error = str(exc)
            state.logs.append(f"✗  Erreur : {exc}")
        finally:
            root_logger.removeHandler(handler)

    async def _async_run(
        self, state: InvestigationState, config: dict[str, Any]
    ) -> None:
        bus = EventBus()
        store = InMemoryGraphStore()

        async def _on_any(event: EntityDiscovered) -> None:
            store.add_event(event)

        for t in (
            "username", "email", "phone", "domain", "url", "ip",
            "account", "person", "location", "image",
        ):
            bus.subscribe(t, _on_any, dedup=False)

        caps = _probe_capabilities()
        use_maigret = bool(config.get("maigret")) and caps["maigret"]
        enrich = bool(config.get("enrich"))
        use_holehe = bool(config.get("holehe")) and caps["holehe"]

        if state.target_type == "username":
            if use_maigret:
                MaigretCollector(
                    bus,
                    top_sites=int(config.get("maigret_top", 500)),
                    timeout=int(config.get("timeout", 30)),
                ).register()
                state.logs.append("• Maigret activé (usernames sur 3000+ sites)")
            else:
                DemoUsernameCollector(bus).register()
                state.logs.append("• Collecteur démo (simulé)")

        if enrich:
            ProfileEnrichmentCollector(bus).register()
            AvatarHashCollector(bus, relationship_sink=store).register()
            GravatarCollector(bus).register()
            EmailDomainExtractor(bus).register()
            state.logs.append("• Enrichissement actif (profils + avatars + domaines)")

        if use_holehe:
            HoleheCollector(bus).register()
            state.logs.append("⚠  Holehe actif — envoi de requêtes à 120+ services")

        # Seed the investigation
        if state.target_type == "email":
            seed = Email(
                value=state.target,
                evidence=[Evidence(collector="user_input", confidence=1.0)],
            )
        else:
            seed = Username(
                value=state.target,
                evidence=[Evidence(collector="user_input", confidence=1.0)],
            )

        await bus.publish(
            EntityDiscovered(entity=seed, origin_collector="user_input")
        )
        await bus.drain()

        if state.cancelled:
            return

        # Finalize: snapshot summary, render graph, save JSON report
        state.summary = store.summary()

        graph_path = self._tmp_dir / f"graph-{state.id}.html"
        graph_path.write_text(
            render_html(store, target=state.target), encoding="utf-8"
        )
        state.graph_html_path = str(graph_path)
        state.logs.append(f"• Graphe généré")

        report_path = self._tmp_dir / f"report-{state.id}.json"
        report_payload = {
            "target": state.target,
            "target_type": state.target_type,
            "summary": state.summary,
            "entities": [e.model_dump(mode="json") for e in store.all()],
            "relationships": [r.model_dump(mode="json") for r in store.relationships],
        }
        report_path.write_text(
            json.dumps(report_payload, indent=2, default=str), encoding="utf-8"
        )
        state.report_json_path = str(report_path)
        state.logs.append(f"• Rapport JSON sauvegardé")
