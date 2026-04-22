"""Vision-based collectors — perceptual image analysis.

Currently:
  - AvatarHashCollector: downloads account avatars, computes perceptual
    hashes, correlates accounts with identical/similar avatars via
    `same_avatar_as` relationships.

Planned:
  - CLIP reverse image search (sentence-transformers)
  - Face embedding & clustering (InsightFace / face_recognition)
  - Image geolocation (StreetCLIP-style)
"""

from osint_core.collectors.vision.avatar_hash import AvatarHashCollector

__all__ = ["AvatarHashCollector"]
