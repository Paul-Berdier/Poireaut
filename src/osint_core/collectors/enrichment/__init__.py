"""Enrichment collectors — take an existing entity and extract sub-entities.

The most common pattern: we have an Account (profile URL + username), we
fetch the profile's public data (via API or HTML), and we extract emails,
links, locations, etc. from the bio / description text. Those sub-entities
cascade back onto the bus and can trigger further collectors.

  * ProfileEnrichmentCollector — GitHub / GitLab / Gravatar API + HTML fallback.
  * GitHubCommitsCollector     — public commit authors on GitHub (email leak).
  * KeybaseCollector           — cryptographic cross-platform proofs.
  * HackerNewsCollector        — HN karma + bio enrichment.
"""

from osint_core.collectors.enrichment.github_commits import GitHubCommitsCollector
from osint_core.collectors.enrichment.hackernews import HackerNewsCollector
from osint_core.collectors.enrichment.keybase import KeybaseCollector
from osint_core.collectors.enrichment.profile import ProfileEnrichmentCollector

__all__ = [
    "GitHubCommitsCollector",
    "HackerNewsCollector",
    "KeybaseCollector",
    "ProfileEnrichmentCollector",
]
