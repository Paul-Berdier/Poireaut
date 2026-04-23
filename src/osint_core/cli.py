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
from osint_core.collectors.username.http_checker import HttpUsernameCollector
from osint_core.collectors.username.maigret_collector import MaigretCollector
from osint_core.collectors.username.whatsmyname import (
    WhatsMyNameCollector,
    fetch_and_cache_wmn,
)
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
              "account", "person", "location", "image", "organization"):
        bus.subscribe(t, _on_any, dedup=False)  # store must see every publish

    # Wire collectors — always use real HTTP checker + WhatsMyName catalog
    HttpUsernameCollector(bus).register()
    WhatsMyNameCollector(bus).register()
    if use_maigret:
        MaigretCollector(bus, top_sites=top, timeout=timeout).register()

    if enrich:
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
        # Domain enrichment — DNS, WHOIS, CT logs, plus subdomain promotion.
        DomainLookupCollector(bus).register()
        SubdomainExtractor(bus, relationship_sink=store).register()
        FrenchCompanyLookupCollector(bus, relationship_sink=store).register()

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
        Organization, Person, Phone, Url, Username,
    )
    from osint_core.entities.graph import Relationship

    payload = json.loads(report.read_text(encoding="utf-8"))
    store = InMemoryGraphStore()

    type_map = {
        "username": Username, "email": Email, "phone": Phone,
        "domain": Domain, "url": Url, "ip": IpAddress,
        "account": Account, "person": Person, "location": Location,
        "image": ImageAsset, "organization": Organization,
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


@app.command(name="update-wmn")
def update_wmn(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Override the cache path. Defaults to ~/.cache/osint-core/wmn-data.json.",
    ),
) -> None:
    """Fetch the latest WhatsMyName database (600+ sites) into the user cache.

    Source: https://github.com/WebBreacher/WhatsMyName (CC-BY 4.0).
    The bundled fallback covers ~18 sites; running this unlocks the full catalog.
    """
    _setup_logging(False)
    console.rule("[bold cyan]Updating WhatsMyName catalog")
    try:
        path = asyncio.run(fetch_and_cache_wmn(cache_path=output))
    except Exception as exc:
        console.print(f"[bold red]✗[/bold red] Failed: {exc}")
        raise typer.Exit(1) from exc

    # Summarize what we just wrote.
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        n = len(payload.get("sites") or [])
    except Exception:
        n = -1
    console.print(
        f"[bold green]✓[/bold green] Wrote [bold]{path}[/bold]"
        + (f" ({n} sites)" if n >= 0 else "")
    )


@app.command(name="company")
def company_cmd(
    query: str = typer.Argument(
        ..., help="Company name, SIREN (9 digits) or SIRET (14 digits)."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Look up a French legal entity via the public gouv.fr registry.

    Uses https://recherche-entreprises.api.gouv.fr — no API key required.
    Returns the SIREN, legal form, head office address, and directors
    who haven't opted out of SIRENE/RNE diffusion.
    """
    import httpx

    _setup_logging(verbose)
    console.rule(f"[bold cyan]Querying French registry: {query}")

    # If the query is numeric and 9 or 14 digits, formulate it as a SIREN search.
    cleaned = query.replace(" ", "")
    if cleaned.isdigit() and len(cleaned) in (9, 14):
        params = {"q": f"siren:{cleaned[:9]}", "per_page": "1"}
    else:
        params = {"q": query, "per_page": "3"}

    url = "https://recherche-entreprises.api.gouv.fr/search"
    try:
        r = httpx.get(
            url,
            params=params,
            headers={
                "User-Agent": "osint-core/0.1 (research)",
                "Accept": "application/json",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        console.print(f"[bold red]✗[/bold red] Network error: {exc}")
        raise typer.Exit(1) from exc

    if r.status_code != 200:
        console.print(
            f"[bold red]✗[/bold red] HTTP {r.status_code}: {r.text[:200]}"
        )
        raise typer.Exit(1)

    data = r.json()
    results = data.get("results") or []
    if not results:
        console.print("[yellow]No match found.[/yellow]")
        raise typer.Exit(0)

    from rich.table import Table as _RTable
    for hit in results[:3]:
        siren = hit.get("siren", "?")
        nom = hit.get("nom_complet") or hit.get("nom_raison_sociale") or "?"
        forme = hit.get("nature_juridique", "")
        creation = hit.get("date_creation", "")
        siege = hit.get("siege") or {}
        address = siege.get("geo_adresse", "") or (
            f"{siege.get('code_postal', '')} {siege.get('libelle_commune', '')}"
        ).strip()
        etat = hit.get("etat_administratif", "")
        state_label = "Active" if etat == "A" else ("Ceased" if etat == "C" else etat)

        console.rule(f"[bold]{nom}[/bold] · SIREN {siren}")
        meta = _RTable(show_header=False, box=None, pad_edge=False)
        meta.add_column(style="dim", no_wrap=True)
        meta.add_column()
        meta.add_row("Legal form", forme or "—")
        meta.add_row("Status", state_label or "—")
        meta.add_row("Created", creation or "—")
        meta.add_row("Address", address or "—")
        meta.add_row(
            "Annuaire",
            f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}",
        )
        console.print(meta)

        dirigeants = [d for d in (hit.get("dirigeants") or []) if d.get("nom")]
        if dirigeants:
            dt = _RTable(title="Dirigeants", show_header=True, pad_edge=False)
            dt.add_column("Name", style="cyan")
            dt.add_column("Role")
            dt.add_column("Born", justify="right", style="dim")
            for d in dirigeants:
                full = f"{d.get('prenoms') or ''} {d.get('nom') or ''}".strip()
                dt.add_row(
                    full.title(),
                    d.get("qualite") or "—",
                    str(d.get("annee_de_naissance") or "—"),
                )
            console.print(dt)


@app.command()
def version() -> None:
    """Show version info."""
    from osint_core import __version__

    console.print(f"osint-core [bold]{__version__}[/bold]")


if __name__ == "__main__":
    app()
