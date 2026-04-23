"""Email-based collectors.

Inputs: Email entities (usually emitted by ProfileEnrichmentCollector after
parsing a bio, or by the user as a seed).

Outputs: Domain entities, Account entities for services where the email
is registered (Gravatar, Holehe-discovered services), additional emails
bound to the same PGP key, and — through cascading — everything those
trigger.

The most interesting cascade in the system:

    Email  -->  Gravatar  -->  Account(platform=gravatar, avatar_url)
           |                                |
           |                                +--> ProfileEnrichment
           |                                |      |
           |                                |      +--> more emails, urls, location
           |                                |
           |                                +--> AvatarHashCollector
           |                                       |
           |                                       +--> same_avatar_as edges
           |                                            to all other accounts
           |                                            sharing that avatar
           |
           +--> PgpKeyCollector --> Email(s) bound to same PGP key
                                       (pgp_bound_to edges)
"""

from osint_core.collectors.email.domain_extractor import EmailDomainExtractor
from osint_core.collectors.email.gravatar import GravatarCollector
from osint_core.collectors.email.holehe_collector import HoleheCollector
from osint_core.collectors.email.pgp_key import PgpKeyCollector

__all__ = [
    "EmailDomainExtractor",
    "GravatarCollector",
    "HoleheCollector",
    "PgpKeyCollector",
]
