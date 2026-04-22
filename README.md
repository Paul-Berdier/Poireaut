# osint-core

Modular OSINT investigation toolkit with a publish/subscribe collector
architecture, ready to be extended with AI-powered correlation.

> **⚠️ Éthique & Légalité**
> Cet outil est destiné à l'apprentissage, à la recherche en sécurité défensive,
> à la protection de votre propre empreinte numérique, et aux investigations
> autorisées (journalisme, OSINT éthique type TraceLabs). Respectez le RGPD,
> les conditions d'utilisation des plateformes, et ne l'utilisez **jamais**
> pour harceler, doxer, ou cibler des individus sans consentement ou mandat
> légitime.

## Pourquoi un énième outil OSINT ?

Les outils existants (SpiderFoot, Sherlock, Maigret, Recon-ng…) sont soit
abandonnés, soit trop monolithiques, soit purement déterministes — aucun
n'intègre de raisonnement IA. Ce projet vise à :

1. Orchestrer les meilleures libs OSINT existantes derrière **un modèle
   d'entités unifié**
2. Fournir un **bus pub/sub async** où chaque collecteur est un plugin
3. Poser les bases d'une **couche de corrélation ML** (embeddings,
   stylométrie, reverse image search, synthèse LLM)

## Architecture en un coup d'œil

```
        ┌──────────────────────────────────────┐
        │ CLI / API (typer, fastapi plus tard) │
        └────────────────┬─────────────────────┘
                         │ seed entity (username, email…)
                         ▼
                ┌────────────────┐
                │   EventBus     │  ←─────┐
                │  (pub/sub)     │        │ emit()
                └────┬────┬──────┘        │
                     │    │               │
              ┌──────┘    └───────┐       │
              ▼                   ▼       │
    ┌──────────────────┐  ┌───────────────┴─────┐
    │ MaigretCollector │  │ (future collectors) │
    │  consumes: user  │  │  EXIF, email, IP... │
    │  produces: acct  │  └─────────────────────┘
    └──────────────────┘
              │ merged entities
              ▼
        ┌──────────────┐
        │ GraphStore   │  → report (JSON, graph viz, PDF)
        └──────────────┘
```

Clés du design :

- **Entity** = nœud du graphe d'investigation. Chaque entité porte une liste
  d'`Evidence` (provenance, source, confiance) — on ne stocke jamais un fait
  sans sa source.
- **dedup_key** : deux entités trouvées par deux collecteurs différents mais
  qui désignent la même chose du monde réel sont fusionnées automatiquement.
- **Collector** : un plugin déclaratif. Il annonce `consumes` et `produces`,
  et le bus fait le câblage tout seul.
- **Chaînage automatique** : si un collecteur `A` produit des `email`, et
  qu'un collecteur `B` consomme des `email`, la sortie de `A` devient
  l'entrée de `B` sans code supplémentaire.

## Installation

Python 3.11+ requis.

```bash
git clone <ton-repo>/osint-core.git
cd osint-core
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # mode dev avec tests
pip install -e ".[maigret]"        # + intégration Maigret réelle
```

## Utilisation

**Mode démo** (sans dépendance externe, données factices) :
```bash
osint investigate alice
```

**Avec enrichment** (fetch GitHub/GitLab/Gravatar APIs, extrait emails/URLs/localisations depuis les bios, hash perceptuels des avatars, résolution domain pour chaque email) :
```bash
osint investigate alice --enrich
osint investigate alice --maigret --enrich -o report.json
```

**Avec Holehe** (⚠️ envoie des requêtes password-reset à 120+ sites pour chaque email) :
```bash
pip install -e ".[email-lookup]"
osint investigate alice --maigret --enrich --holehe
```

Pour contourner le rate limit GitHub (60 req/h), exporte un token :
```bash
export GITHUB_TOKEN=ghp_xxx
```

**Mode Maigret réel** (3000+ sites, plusieurs minutes) :
```bash
osint investigate alice --maigret --top 500
osint investigate alice --maigret --top 3000 --timeout 45 -o report.json
```

**Visualisation graphe interactive** (HTML standalone, ouvrir dans un navigateur) :
```bash
# Pipeline d'investigation + render HTML en une passe
osint investigate alice --maigret --enrich --graph alice.html

# Re-render un report JSON déjà sauvegardé
osint graph alice_report.json -o alice.html
```

Le viewer généré embarque toutes les données (aucun serveur requis), affiche :
- **Graphe interactif** Cytoscape.js avec layouts organique / radial / hiérarchique
- **Filtres par type** d'entité cliquables
- **Recherche** par valeur (raccourci `/`)
- **Panneau détails** complet à la sélection : évidence, sources, provenance
- **Surlignage du voisinage** au survol pour tracer les chaînes de déduction

**Détail :**
```bash
osint investigate alice -v             # logs debug
osint investigate alice -o report.json # rapport JSON complet
```

## Étendre : ajouter un collecteur

Exemple — un collecteur qui enrichit une `Username` en allant chercher
l'avatar Gravatar si on trouve plus tard un email associé :

```python
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import ImageAsset

class GravatarCollector(BaseCollector):
    name = "gravatar"
    consumes = ["email"]
    produces = ["image"]

    async def collect(self, event):
        import hashlib, httpx
        email = event.entity.value
        h = hashlib.md5(email.encode()).hexdigest()
        url = f"https://www.gravatar.com/avatar/{h}?d=404"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
        if r.status_code == 200:
            await self.emit(
                ImageAsset(
                    value=url,
                    evidence=[Evidence(
                        collector=self.name, source_url=url, confidence=0.9
                    )],
                ),
                event,
            )
```

Register it once in `cli.py` and the bus auto-wires it into any flow that
produces `email` entities.

## Feuille de route

- [x] **Phase 0** — socle : entités, bus, stockage, CLI, collecteur démo
- [x] **Phase 1.0** — wrapper Maigret pour usernames
- [x] **Phase 1.1** — enrichment profils (GitHub/GitLab API + HTML générique)
- [x] **Phase 1.2** — extracteurs : emails, URLs, handles, locations (gazetteer)
- [x] **Phase 2.0** — relations auto-générées + visualisation HTML interactive
- [x] **Phase 3.0** — premier module IA : hash perceptuel avatars
      → arêtes sémantiques `same_avatar_as` entre comptes visuellement liés
- [x] **Phase 4.0** — collecteurs email : Domain extractor (+ disposable flag),
      Gravatar (email→account→enrichment cascade), Holehe (optionnel)
- [ ] **Phase 3.1** — CLIP reverse image search (embeddings sémantiques)
- [ ] **Phase 3.2** — stylométrie : embeddings de bios pour "même auteur"
- [ ] **Phase 3.3** — NER transformer pour remplacer le gazetteer
- [ ] **Phase 4.1** — HIBP (breaches) + MX validation + SMTP probe
- [ ] **Phase 4.2** — backend Neo4j
- [ ] **Phase 5** — moteur de corrélation YAML style SpiderFoot + synthèse LLM
- [ ] **Phase 6** — orchestrateur agentique (LLM planifie le DAG d'investigation)

## Extras optionnels

```bash
pip install -e ".[vision]"       # imagehash + Pillow pour avatars
pip install -e ".[maigret]"      # Maigret réel (3000+ sites)
pip install -e ".[dev]"          # tests + linters
```

## Tests

```bash
pytest
```

## Licence

MIT.
