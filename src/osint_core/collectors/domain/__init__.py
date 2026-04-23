"""Domain-centric collectors.

  * DomainLookupCollector  — DNS (A/MX/TXT), CT logs, WHOIS.
  * SubdomainExtractor     — promotes CT-observed subdomains to Domain nodes.
"""

from osint_core.collectors.domain.lookup import DomainLookupCollector
from osint_core.collectors.domain.subdomain_extractor import SubdomainExtractor

__all__ = ["DomainLookupCollector", "SubdomainExtractor"]
