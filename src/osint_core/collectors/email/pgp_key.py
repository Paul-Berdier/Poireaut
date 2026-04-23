"""Public PGP keyserver collector.

Consumes: Email entities
Produces: Email entities (additional addresses bound to the same key),
          pgp_bound_to relationships.

`keys.openpgp.org` (the Hagrid keyserver used by default by GnuPG since 2019)
exposes a public REST endpoint to look up verified OpenPGP keys by email:

    GET https://keys.openpgp.org/vks/v1/by-email/{email}

Returns either an ASCII-armored public key block (Content-Type:
application/pgp-keys) or 404. The returned key encodes one or more User IDs
(UIDs), each of the form:

    "Alice Example <alice@example.org>"

We parse the ASCII-armored packet stream manually — no need to pull in
python-gnupg or `gpg` as a dependency for this one operation. For each UID
we find:
  * If it contains an email different from the seed, we emit that Email.
  * We link all emails on a single key via `pgp_bound_to` edges (the key
    is a cryptographic anchor that ties them all to the same keyholder).

Ethics:
  * Keyservers are explicitly public infrastructure — their whole purpose
    is unauthenticated lookup. keys.openpgp.org goes further: since 2019,
    an email only appears on a key after the keyholder explicitly consents
    via email confirmation. Any address reachable via this endpoint was
    deliberately published by the keyholder.
  * We only perform GET requests — no uploads, no deletions.
"""

from __future__ import annotations

import base64
import logging
import re
import urllib.parse
from typing import ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.identifiers import Email

log = logging.getLogger(__name__)


# UID on a public key is of the form:  Name (comment) <email@domain>
# We accept the bare-email form too.
_UID_EMAIL_RE = re.compile(
    r"(?:([^\n<>]+?)\s*)?<([^<>@\s]+@[^<>@\s]+\.[^<>@\s]+)>"
    r"|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24})"
)


class PgpKeyCollector(BaseCollector):
    """Resolve an email to its public PGP key and emit bound identities."""

    name = "pgp_key"
    consumes: ClassVar[list[str]] = ["email"]
    produces: ClassVar[list[str]] = ["email"]

    KEYSERVER_URL: ClassVar[str] = "https://keys.openpgp.org/vks/v1/by-email/"

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 15.0,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout

    async def collect(self, event: EntityDiscovered) -> None:
        email = event.entity
        if not isinstance(email, Email):
            return

        armored = await self._fetch_key(email.value)
        if armored is None:
            return

        uids = self._extract_uids(armored)
        if not uids:
            self.log.debug("pgp_key: no UIDs parsed from key of %s", email.value)
            return

        self.log.info(
            "pgp_key: %s has a public key on keys.openpgp.org with %d UID(s)",
            email.value, len(uids),
        )

        # The lookup itself is useful metadata — write it on the seed email.
        if email.metadata.get("has_pgp_key") is None:
            email.metadata["has_pgp_key"] = True

        emitted_emails: list[Email] = []
        for name, candidate_email in uids:
            if not candidate_email:
                continue
            if candidate_email == email.value:
                continue
            try:
                new_email = Email(
                    value=candidate_email,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=self.KEYSERVER_URL + urllib.parse.quote(email.value),
                            # Strong signal: the keyholder actively confirmed
                            # control of this address via a signed email from
                            # keys.openpgp.org's verification flow.
                            confidence=0.88,
                            notes=(
                                f"Bound to same PGP key as {email.value}"
                                + (f" (UID name: {name})" if name else "")
                            ),
                            raw_data={"uid_name": name, "anchor_email": email.value},
                        )
                    ],
                    metadata={"has_pgp_key": True, "anchor_email": email.value},
                )
            except ValueError:
                self.log.debug(
                    "pgp_key: rejected malformed email %r", candidate_email
                )
                continue
            await self.emit(new_email, event)
            emitted_emails.append(new_email)

        # Pairwise pgp_bound_to edges between the seed and every emitted email.
        for bound in emitted_emails:
            self.emit_relationship(
                Relationship(
                    source_id=email.id,
                    target_id=bound.id,
                    predicate="pgp_bound_to",
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=self.KEYSERVER_URL
                            + urllib.parse.quote(email.value),
                            confidence=0.88,
                            notes="Both addresses listed as UIDs on the same public PGP key",
                        )
                    ],
                )
            )

    async def _fetch_key(self, email_value: str) -> str | None:
        """Fetch the ASCII-armored key for an email, or None on miss/error."""
        url = self.KEYSERVER_URL + urllib.parse.quote(email_value)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                r = await client.get(
                    url,
                    headers={
                        "User-Agent": "osint-core/0.1 (research)",
                        "Accept": "application/pgp-keys, text/plain",
                    },
                )
        except httpx.HTTPError as exc:
            self.log.debug("pgp_key: network error for %s: %s", email_value, exc)
            return None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            self.log.debug(
                "pgp_key: HTTP %d for %s", r.status_code, email_value
            )
            return None
        text = r.text
        if "-----BEGIN PGP PUBLIC KEY BLOCK-----" not in text:
            return None
        return text

    @classmethod
    def _extract_uids(cls, armored: str) -> list[tuple[str | None, str | None]]:
        """Parse UIDs out of an ASCII-armored OpenPGP key block.

        We operate on the raw binary of the key (after base64-decoding the
        armor body) and walk its packet structure, harvesting the contents
        of every User ID packet (tag=13). This avoids pulling in a full
        OpenPGP library and handles both V4 and V5 packet formats.

        Falls back to a plain-text UID regex sweep if the binary parse
        encounters anything unexpected — keyserver-returned keys are
        well-formed in practice, but we prefer graceful degradation.
        """
        # 1) Strip armor, dearmor.
        lines = armored.splitlines()
        body: list[str] = []
        in_block = False
        in_headers = False
        for line in lines:
            if line.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"):
                in_block = True
                in_headers = True
                continue
            if line.startswith("-----END PGP PUBLIC KEY BLOCK-----"):
                break
            if not in_block:
                continue
            if in_headers:
                # Armor headers end with a blank line
                if line.strip() == "":
                    in_headers = False
                continue
            if line.startswith("="):  # CRC24 checksum line
                continue
            body.append(line.strip())

        if not body:
            return cls._regex_fallback(armored)

        try:
            raw = base64.b64decode("".join(body))
        except Exception:
            return cls._regex_fallback(armored)

        uids: list[tuple[str | None, str | None]] = []
        offset = 0
        n = len(raw)
        max_packets = 256  # safety bound

        while offset < n and len(uids) + 0 < max_packets:
            # Packet header: byte 0 tells us tag + length format.
            try:
                header = raw[offset]
            except IndexError:
                break
            if header & 0x80 == 0:
                break  # invalid packet marker

            is_new_format = bool(header & 0x40)
            if is_new_format:
                tag = header & 0x3F
                offset += 1
                if offset >= n:
                    break
                first = raw[offset]
                if first < 192:
                    packet_len = first
                    offset += 1
                elif first < 224:
                    if offset + 1 >= n:
                        break
                    packet_len = ((first - 192) << 8) + raw[offset + 1] + 192
                    offset += 2
                elif first == 255:
                    if offset + 4 >= n:
                        break
                    packet_len = int.from_bytes(raw[offset + 1 : offset + 5], "big")
                    offset += 5
                else:
                    # Partial body lengths: we just walk to the next clean packet.
                    # For our purposes (harvesting UIDs), skip this packet entirely.
                    packet_len = 1 << (first & 0x1F)
                    offset += 1
            else:
                tag = (header >> 2) & 0x0F
                length_type = header & 0x03
                offset += 1
                if length_type == 0:
                    if offset >= n:
                        break
                    packet_len = raw[offset]
                    offset += 1
                elif length_type == 1:
                    if offset + 1 >= n:
                        break
                    packet_len = int.from_bytes(raw[offset : offset + 2], "big")
                    offset += 2
                elif length_type == 2:
                    if offset + 3 >= n:
                        break
                    packet_len = int.from_bytes(raw[offset : offset + 4], "big")
                    offset += 4
                else:
                    # Indeterminate length — skip rest of stream safely.
                    break

            end = offset + packet_len
            if end > n:
                break

            # Tag 13 == User ID packet (per RFC 4880 §5.11)
            if tag == 13:
                try:
                    uid_str = raw[offset:end].decode("utf-8", errors="replace")
                except Exception:
                    uid_str = ""
                for match in _UID_EMAIL_RE.finditer(uid_str):
                    name = (match.group(1) or "").strip() or None
                    mail = (match.group(2) or match.group(3) or "").strip().lower() or None
                    uids.append((name, mail))

            offset = end

        # If the binary parse found nothing, fall back to a regex sweep.
        if not uids:
            return cls._regex_fallback(armored)
        return uids

    @staticmethod
    def _regex_fallback(armored: str) -> list[tuple[str | None, str | None]]:
        """Last-resort: regex-scan the armored text for UID-shaped strings.

        Armor headers sometimes include the keyholder's email in plain text;
        pickup there is far from complete but helps when the packet parser
        bails out on a malformed or experimental key format.
        """
        found: list[tuple[str | None, str | None]] = []
        for match in _UID_EMAIL_RE.finditer(armored):
            name = (match.group(1) or "").strip() or None
            mail = (match.group(2) or match.group(3) or "").strip().lower() or None
            if mail:
                found.append((name, mail))
        return found
