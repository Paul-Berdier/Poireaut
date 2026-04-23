"""Phone number analysis collector.

Extracts metadata from a phone number using Google's libphonenumber
(via the `phonenumbers` Python package — pure Python, no API needed):
  - Country / region
  - Carrier name
  - Line type (mobile, fixed, VoIP, etc.)
  - Timezone(s)
  - Validity check

Then optionally hits free APIs for enrichment:
  - numverify.com (free tier, 100 req/month, no key needed for basic)
"""

from __future__ import annotations

import logging
from typing import ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Phone
from osint_core.entities.profiles import Location

log = logging.getLogger(__name__)


class PhoneLookupCollector(BaseCollector):
    name = "phone_lookup"
    consumes: ClassVar[list[str]] = ["phone"]
    produces: ClassVar[list[str]] = ["location"]

    async def collect(self, event: EntityDiscovered) -> None:
        phone = event.entity
        if not isinstance(phone, Phone):
            return

        raw = phone.value

        try:
            import phonenumbers
            from phonenumbers import carrier, geocoder, timezone
        except ImportError:
            self.log.error("phonenumbers not installed. pip install phonenumbers")
            return

        try:
            parsed = phonenumbers.parse(raw, None)
        except phonenumbers.NumberParseException:
            self.log.warning("cannot parse phone: %s", raw)
            phone.metadata["valid"] = False
            phone.metadata["confidence_score"] = 10
            return

        is_valid = phonenumbers.is_valid_number(parsed)
        is_possible = phonenumbers.is_possible_number(parsed)

        country_code = parsed.country_code
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        international = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)

        # Carrier
        carrier_name = carrier.name_for_number(parsed, "en") or "Unknown"

        # Number type
        num_type_map = {
            phonenumbers.PhoneNumberType.MOBILE: "mobile",
            phonenumbers.PhoneNumberType.FIXED_LINE: "fixed_line",
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
            phonenumbers.PhoneNumberType.VOIP: "voip",
            phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
            phonenumbers.PhoneNumberType.PREMIUM_RATE: "premium_rate",
            phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "personal",
            phonenumbers.PhoneNumberType.PAGER: "pager",
        }
        num_type = num_type_map.get(
            phonenumbers.number_type(parsed), "unknown"
        )

        # Geolocation
        geo_desc = geocoder.description_for_number(parsed, "en") or ""
        country_name = geocoder.country_name_for_number(parsed, "en") or ""

        # Timezones
        tzs = list(timezone.time_zones_for_number(parsed))

        # Confidence
        if is_valid:
            confidence = 85
        elif is_possible:
            confidence = 50
        else:
            confidence = 15

        # Update the phone entity with all metadata
        phone.metadata.update({
            "valid": is_valid,
            "possible": is_possible,
            "country_code": f"+{country_code}",
            "national_format": national,
            "international_format": international,
            "carrier": carrier_name,
            "line_type": num_type,
            "geo_description": geo_desc,
            "country": country_name,
            "timezones": tzs,
            "confidence_score": confidence,
        })

        self.log.info(
            "phone %s: %s, carrier=%s, type=%s, country=%s (conf=%d%%)",
            raw, "valid" if is_valid else "invalid",
            carrier_name, num_type, country_name, confidence,
        )

        # Emit a Location if we got geographic info
        if geo_desc or country_name:
            loc = Location(
                value=geo_desc or country_name,
                country=country_name,
                city=geo_desc if geo_desc != country_name else None,
                evidence=[
                    Evidence(
                        collector=self.name,
                        confidence=confidence / 100,
                        notes=f"Phone geolocation for {international} ({carrier_name}, {num_type})",
                        raw_data=phone.metadata,
                    )
                ],
            )
            await self.emit(loc, event)
