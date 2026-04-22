"""Enrichment collectors — take an existing entity and extract sub-entities.

The most common pattern: we have an Account (profile URL + username), we
fetch the profile's public data (via API or HTML), and we extract emails,
links, locations, etc. from the bio / description text. Those sub-entities
cascade back onto the bus and can trigger further collectors.
"""

from osint_core.collectors.enrichment.profile import ProfileEnrichmentCollector

__all__ = ["ProfileEnrichmentCollector"]
