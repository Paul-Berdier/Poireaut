"""Command-line interface for running OSINT investigations.

Examples
--------
    osint investigate alice               # demo mode (works out of the box)
    osint investigate alice --maigret     # real Maigret search
    osint investigate alice -o report.json
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

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
from osint_core.entities.identifiers import Username
from osint_core.storage.memory import InMemoryGraphStore
from osint_core.visualization import render_html

app = typer.Typer(
    help="Modular OSINT investigation toolkit.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


async def _run(
    username: str,
    use_maigret: bool,
    top: int,
    timeout: int,
    enrich: bool,
    holehe: bool = False,
) -> InMemoryGraphStore:
    bus = EventBus()
    store = InMemoryGraphStore()

    # Subscribe the store to every entity type we care about.
    async def _on_any(event: EntityDiscovered) -> None:
        store.add_event(event)  # adds entity + auto-creates derived_from edge

    for t in ("username", "email", "phone", "domain", "url", "ip",
              "account", "person", "location", "image"):
        bus.subscribe(t, _on_any, dedup=False)  # store must see every publish

    # Wire collectors
    if use_maigret:
        MaigretCollector(bus, top_sites=top, timeout=timeout).register()
    else:
        DemoUsernameCollector(bus).register()

    if enrich:
        ProfileEnrichmentCollector(bus).register()
        AvatarHashCollector(bus, relationship_sink=store).register()
        GravatarCollector(bus).register()
        EmailDomainExtractor(bus).register()

    if holehe:
        HoleheCollector(bus).register()

    seed = Username(
        value=username,
        evidence=[Evidence(collector="user_input", confidence=1.0)],
    )
    await bus.publish(
        EntityDiscovered(entity=seed, origin_collector="user_input")
    )
    await bus.drain()
    return store


@app.command()
def investigate(
    username: str = typer.Argument(..., help="Username to investigate."),
    maigret: bool = typer.Option(
        False,
        "--maigret/--demo",
        help="Use real Maigret (3000+ sites, requires install) or demo mode.",
    ),
    enrich: bool = typer.Option(
        False,
        "--enrich/--no-enrich",
        help="Fetch each account's profile (GitHub/GitLab/Gravatar), extract sub-entities, hash avatars, resolve email domains.",
    ),
    holehe: bool = typer.Option(
        False,
        "--holehe",
        help="[Aggressive] Probe 120+ sites via password-reset flows for every email. Sends real HTTP requests to the targets. Requires 'pip install osint-core[email-lookup]'.",
    ),
    top: int = typer.Option(500, help="[Maigret] Check top-N sites by popularity."),
    timeout: int = typer.Option(30, help="[Maigret] Per-site timeout seconds."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write JSON report to this path."
    ),
    graph: Path | None = typer.Option(
        None, "--graph", "-g", help="Render an interactive HTML graph to this path."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Investigate a username across the internet."""
    _setup_logging(verbose)
    bits = ['maigret' if maigret else 'demo']
    if enrich: bits.append('+enrich')
    if holehe: bits.append('+holehe')
    mode = " ".join(bits)
    console.rule(f"[bold cyan]Investigating username: {username} [{mode}]")

    store = asyncio.run(_run(username, maigret, top, timeout, enrich, holehe))

    summary = store.summary()
    console.print()
    console.print(f"[bold green]✓ Investigation complete[/bold green]")
    console.print(f"[dim]Entities: {summary}[/dim]\n")

    accounts = store.by_type("account")
    if accounts:
        table = Table(title="Accounts discovered", show_lines=False)
        table.add_column("Platform", style="cyan", no_wrap=True)
        table.add_column("Username", style="magenta")
        table.add_column("Display name", style="white")
        table.add_column("URL", style="blue")
        table.add_column("Conf", justify="right")
        for acc in sorted(accounts, key=lambda a: -a.confidence):
            table.add_row(
                getattr(acc, "platform", "?") or "?",
                getattr(acc, "username", "?") or "?",
                getattr(acc, "display_name", None) or "",
                getattr(acc, "profile_url", "") or "",
                f"{acc.confidence:.2f}",
            )
        console.print(table)

    for entity_type, title, style in [
        ("email", "Emails", "yellow"),
        ("url", "URLs (external links from bios)", "blue"),
        ("location", "Locations mentioned", "green"),
        ("username", "Other usernames mentioned", "magenta"),
    ]:
        items = [e for e in store.by_type(entity_type) if e.value != username]
        if not items:
            continue
        t = Table(title=title)
        t.add_column("Value", style=style)
        t.add_column("Confidence", justify="right")
        t.add_column("Discovered by")
        for e in sorted(items, key=lambda x: -x.confidence):
            collectors = ", ".join(sorted({ev.collector for ev in e.evidence}))
            t.add_row(e.value, f"{e.confidence:.2f}", collectors)
        console.print(t)

    if output:
        report = {
            "target": username,
            "mode": mode,
            "summary": summary,
            "entities": [e.model_dump(mode="json") for e in store.all()],
            "relationships": [r.model_dump(mode="json") for r in store.relationships],
        }
        output.write_text(json.dumps(report, indent=2, default=str))
        console.print(f"\n[bold]Report:[/bold] {output.absolute()}")

    if graph:
        html = render_html(store, target=username)
        graph.write_text(html, encoding="utf-8")
        console.print(f"[bold]Graph:[/bold]  {graph.absolute()}")


@app.command(name="graph")
def graph_cmd(
    report: Path = typer.Argument(..., help="JSON report produced by `osint investigate -o`"),
    output: Path = typer.Option(
        Path("investigation.html"), "--output", "-o", help="HTML destination."
    ),
) -> None:
    """Render an interactive HTML graph from a saved JSON report."""
    from osint_core.entities import (
        Account, Domain, Email, ImageAsset, IpAddress, Location,
        Person, Phone, Url, Username,
    )
    from osint_core.entities.graph import Relationship

    payload = json.loads(report.read_text(encoding="utf-8"))
    store = InMemoryGraphStore()

    type_map = {
        "username": Username, "email": Email, "phone": Phone,
        "domain": Domain, "url": Url, "ip": IpAddress,
        "account": Account, "person": Person, "location": Location,
        "image": ImageAsset,
    }
    for e_data in payload.get("entities", []):
        cls = type_map.get(e_data.get("entity_type"))
        if cls is None:
            continue
        try:
            store.add_entity(cls.model_validate(e_data))
        except Exception as exc:
            console.print(f"[yellow]skipped entity: {exc}[/yellow]")

    # Relationships don't go through add_event (no bus events to replay);
    # we insert them directly.
    for r_data in payload.get("relationships", []):
        try:
            store.add_relationship(Relationship.model_validate(r_data))
        except Exception as exc:
            console.print(f"[yellow]skipped relationship: {exc}[/yellow]")

    target = payload.get("target", "")
    html = render_html(store, target=target)
    output.write_text(html, encoding="utf-8")
    console.print(f"[bold green]✓[/bold green] Graph written to [bold]{output.absolute()}[/bold]")


@app.command()
def version() -> None:
    """Show version info."""
    from osint_core import __version__

    console.print(f"osint-core [bold]{__version__}[/bold]")


if __name__ == "__main__":
    app()
