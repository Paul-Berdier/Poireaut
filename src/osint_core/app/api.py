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
from osint_core.collectors.domain import DomainLookupCollector, SubdomainExtractor
from osint_core.collectors.email import (
    EmailDomainExtractor,
    GravatarCollector,
    HoleheCollector,
    PgpKeyCollector,
)
from osint_core.collectors.enrichment import (
    GitHubCommitsCollector,
    HackerNewsCollector,
    KeybaseCollector,
    ProfileEnrichmentCollector,
)
from osint_core.collectors.enrichment.french_company import (
    FrenchCompanyLookupCollector,
)
from osint_core.collectors.enrichment.urlscan import UrlscanCollector
from osint_core.collectors.enrichment.wayback import WaybackCollector
from osint_core.collectors.network import IpLookupCollector
from osint_core.collectors.phone import PhoneLookupCollector
from osint_core.collectors.username.http_checker import HttpUsernameCollector
from osint_core.collectors.username.maigret_collector import (
    MaigretCollector,
    is_maigret_available,
)
from osint_core.collectors.username.whatsmyname import WhatsMyNameCollector
from osint_core.collectors.vision.avatar_hash import AvatarHashCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email, IpAddress, Phone, Username
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
    caps["maigret"] = is_maigret_available() is not None
    try:
        import imagehash  # noqa: F401
        from PIL import Image  # noqa: F401
        caps["vision"] = True
    except Exception:
        pass
    try:
        from holehe.core import import_submodules  # noqa: F401
        caps["holehe"] = True
    except Exception:
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
        self._window = None  # set by main.py after window creation

    def set_window(self, window) -> None:
        """Called by main.py to give us access to the pywebview window."""
        self._window = window

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
          - seeds: list of {value: str, type: "username"|"email"|"phone"|"ip"}
        """
        inv_id = uuid.uuid4().hex[:12]
        seeds = config.get("seeds", [])
        # Build a display target from all seeds
        target_parts = [s.get("value", "") for s in seeds if s.get("value", "").strip()]
        target = ", ".join(target_parts) if target_parts else ""

        state = InvestigationState(
            id=inv_id,
            target=target or "(vide)",
            target_type="multi",
        )
        if not target_parts:
            state.status = "error"
            state.error = "Aucune information fournie"
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

    def save_report(self, inv_id: str) -> dict[str, Any]:
        """Open a native Save-As dialog and write the report there."""
        with self._lock:
            state = self._investigations.get(inv_id)
        if state is None or not state.report_json_path:
            return {"ok": False, "error": "Pas de rapport disponible"}
        if self._window is None:
            return {"ok": False, "error": "Fenetre non disponible"}
        try:
            import webview
            # Use the non-deprecated API if available (pywebview 5.x)
            dialog_type = getattr(webview, "SAVE_DIALOG", None)
            if hasattr(webview, "FileDialog"):
                dialog_type = webview.FileDialog.SAVE
            if dialog_type is None:
                dialog_type = webview.SAVE_DIALOG
            result = self._window.create_file_dialog(
                dialog_type,
                save_filename=f"poireaut-{state.target}.json",
            )
            if not result:
                return {"ok": False, "error": "Annule"}
            dest = result if isinstance(result, str) else result[0]
            Path(dest).write_bytes(Path(state.report_json_path).read_bytes())
            return {"ok": True, "path": str(dest)}
        except Exception as exc:
            log.warning("save_report dialog failed: %s", exc)
            # Fallback: return the temp path
            return {"ok": True, "path": state.report_json_path, "fallback": True}

    def open_graph(self, inv_id: str) -> dict[str, Any]:
        """Open the investigation graph in the system's default browser."""
        with self._lock:
            state = self._investigations.get(inv_id)
        if state is None or not state.graph_html_path:
            return {"ok": False, "error": "Graphe non disponible"}
        try:
            import webbrowser
            webbrowser.open(f"file:///{state.graph_html_path}")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_graph_html(self, inv_id: str) -> str | None:
        """Return graph HTML as string (for iframe srcdoc fallback)."""
        with self._lock:
            state = self._investigations.get(inv_id)
        if state is None or not state.graph_html_path:
            return None
        try:
            return Path(state.graph_html_path).read_text(encoding="utf-8")
        except Exception:
            return None

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
            "account", "person", "location", "image", "organization",
        ):
            bus.subscribe(t, _on_any, dedup=False)

        caps = _probe_capabilities()

        # --- ALL collectors always active ---
        HttpUsernameCollector(bus).register()
        state.logs.append("HTTP checker (50+ sites)")

        WhatsMyNameCollector(bus).register()
        state.logs.append("WhatsMyName (catalogue communautaire)")

        if caps["maigret"]:
            MaigretCollector(bus, top_sites=500, timeout=30).register()
            state.logs.append("Maigret (3000+ sites)")

        ProfileEnrichmentCollector(bus).register()
        AvatarHashCollector(bus, relationship_sink=store).register()
        GravatarCollector(bus).register()
        EmailDomainExtractor(bus).register()
        # Cross-platform correlation & public-data deepening.
        GitHubCommitsCollector(bus, relationship_sink=store).register()
        KeybaseCollector(bus, relationship_sink=store).register()
        HackerNewsCollector(bus).register()
        WaybackCollector(bus).register()
        UrlscanCollector(bus).register()
        PgpKeyCollector(bus, relationship_sink=store).register()
        # Domain: DNS/WHOIS/CT + subdomain promotion + FR company registry.
        DomainLookupCollector(bus).register()
        SubdomainExtractor(bus, relationship_sink=store).register()
        FrenchCompanyLookupCollector(bus, relationship_sink=store).register()
        PhoneLookupCollector(bus).register()
        IpLookupCollector(bus).register()

        if caps["holehe"]:
            HoleheCollector(bus).register()
            state.logs.append("Holehe (120+ services)")

        state.logs.append(
            "Enrichissement + avatars + Keybase + PGP + GitHub commits + sous-domaines"
        )

        # --- Publish ALL seeds ---
        seeds = config.get("seeds", [])
        type_map = {
            "username": Username,
            "email": Email,
            "phone": Phone,
            "ip": IpAddress,
        }
        for s in seeds:
            val = s.get("value", "").strip()
            seed_type = s.get("type", "username")
            cls = type_map.get(seed_type)
            if not cls or not val:
                continue
            try:
                entity = cls(
                    value=val,
                    evidence=[Evidence(collector="user_input", confidence=1.0)],
                )
                await bus.publish(
                    EntityDiscovered(entity=entity, origin_collector="user_input")
                )
                state.logs.append(f"Seed: [{seed_type}] {val}")
            except Exception as exc:
                state.logs.append(f"Seed invalide: {val} ({exc})")

        await bus.drain()

        if state.cancelled:
            return

        # Finalize: snapshot summary, render graph, save JSON report
        state.summary = store.summary()

        # Log detailed results with confidence scores
        state.logs.append("")
        state.logs.append("=== RESULTATS ===")
        type_labels = {
            "account": "Comptes trouves",
            "email": "Emails",
            "phone": "Telephones",
            "ip": "Adresses IP",
            "domain": "Domaines",
            "location": "Localisations",
            "url": "URLs",
            "username": "Pseudos",
            "image": "Images",
        }
        for entity_type, label in type_labels.items():
            entities = store.by_type(entity_type)
            # Skip the seed entity for display
            if entity_type == state.target_type and len(entities) <= 1:
                continue
            if not entities:
                continue
            state.logs.append(f"--- {label} ---")
            for e in sorted(entities, key=lambda x: -x.confidence):
                conf = round(e.confidence * 100)
                meta = e.metadata
                extra = ""
                if entity_type == "account":
                    platform = getattr(e, "platform", "?")
                    url = getattr(e, "profile_url", "")
                    extra = f" ({platform}) {url}"
                elif entity_type == "phone":
                    carrier = meta.get("carrier", "")
                    line = meta.get("line_type", "")
                    country = meta.get("country", "")
                    extra = f" — {carrier}, {line}, {country}" if carrier else ""
                elif entity_type == "ip":
                    city = meta.get("city", "")
                    isp = meta.get("isp", "")
                    proxy = " [VPN/PROXY]" if meta.get("is_proxy") else ""
                    extra = f" — {city}, {isp}{proxy}" if isp else ""
                elif entity_type == "location":
                    country = getattr(e, "country", "")
                    extra = f" ({country})" if country else ""
                elif entity_type == "domain":
                    disp = "JETABLE" if meta.get("disposable") else ""
                    extra = f" [{disp}]" if disp else ""

                state.logs.append(f"  [{conf:3d}%] {e.value}{extra}")

        # Relationships
        rels = store.relationships
        if rels:
            pred_counts: dict[str, int] = {}
            for r in rels:
                pred_counts[r.predicate] = pred_counts.get(r.predicate, 0) + 1
            state.logs.append("--- Liens ---")
            for pred, count in sorted(pred_counts.items()):
                state.logs.append(f"  {pred}: {count}")
        state.logs.append("")

        graph_path = self._tmp_dir / f"graph-{state.id}.html"
        graph_path.write_text(
            render_html(store, target=state.target), encoding="utf-8"
        )
        state.graph_html_path = str(graph_path)

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
