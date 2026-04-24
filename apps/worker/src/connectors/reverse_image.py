"""Reverse image search connector.

Given a PHOTO datapoint (whose `value` is the image URL), this connector
generates three search URLs — one for each of the major free reverse-image
services. We don't scrape the results (none of them expose a stable free
API, and scraping Google Images is a cat-and-mouse game), we just produce
clickable URL findings that the investigator opens manually.

That's the same workflow every OSINT tool uses for this capability:
Epieos, IntelTechniques, ToolIQ, etc. It beats the alternative (a paid
FaceCheck/PimEyes subscription) for the Poireaut target audience.

Input : DataType.PHOTO
Output: 3 × DataType.URL, one per search engine.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus


# The search URL builders. Each takes the image URL and returns a URL the
# investigator can open in a new tab to see the search results.
SEARCH_ENGINES: list[tuple[str, str, str]] = [
    (
        "Google Lens",
        "🔎 Recherche inverse Google Lens",
        # Google Lens is their modern reverse-search endpoint; it does a
        # better job than the old images.google.com/searchbyimage on most
        # image types (faces, products, scenes).
        "https://lens.google.com/uploadbyurl?url={url}",
    ),
    (
        "Yandex Images",
        "🔎 Recherche inverse Yandex (souvent meilleur pour les visages)",
        "https://yandex.com/images/search?rpt=imageview&url={url}",
    ),
    (
        "TinEye",
        "🔎 Recherche inverse TinEye (historique, détecte les copies)",
        "https://tineye.com/search/?url={url}",
    ),
]


@register
class ReverseImageConnector(BaseConnector):
    name = "reverse_image"
    display_name = "Reverse Image — 3 search engines"
    category = ConnectorCategory.IMAGE
    description = (
        "Génère trois liens de recherche inverse pour une image : Google Lens, "
        "Yandex (très efficace pour les visages) et TinEye (détection de copies). "
        "L'enquêteur ouvre chaque lien dans un nouvel onglet pour consulter les "
        "résultats — aucune API payante requise."
    )
    homepage_url = None
    input_types = {DataType.PHOTO}
    output_types = {DataType.URL}
    timeout_seconds = 5   # pure URL construction, near-instant

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.PHOTO:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        image_url = input_value.strip()
        if not image_url.startswith(("http://", "https://")):
            return ConnectorResult(
                error="La valeur doit être une URL d'image (http:// ou https://)"
            )

        encoded = quote_plus(image_url, safe="")
        findings: list[Finding] = []
        for engine_name, note, template in SEARCH_ENGINES:
            search_url = template.format(url=encoded)
            findings.append(
                Finding(
                    data_type=DataType.URL,
                    value=search_url,
                    confidence=1.0,  # The URL itself is deterministic
                    source_url=search_url,
                    extracted_at=now_utc(),
                    notes=note,
                    raw={"engine": engine_name, "image_url": image_url},
                )
            )

        return ConnectorResult(
            findings=findings,
            raw_output={
                "engines": [e[0] for e in SEARCH_ENGINES],
                "image_url": image_url,
            },
        )

    async def healthcheck(self) -> HealthStatus:
        # Nothing to check — we don't talk to any upstream service.
        return HealthStatus.OK
