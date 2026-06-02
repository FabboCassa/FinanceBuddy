"""News source quality registry lookup (Phase 4).

Maps the free-text outlet name a feed reports (e.g. "Barrons.com",
"Reuters Videos", "Insider Monkey") to a curated quality tier + country +
language, so the analysis can default to trustworthy outlets and discard
low-signal aggregators/opinion blogs. Pure functions, no DB — the registry
lives in ``constants.SOURCE_REGISTRY`` and any new feed (RSS, Reddit, …) reuses
the same tiers.
"""
from __future__ import annotations

from core import constants


def source_meta(source_name):
    """Resolve an outlet name to (canonical, tier, country, language).

    Case-insensitive substring match on each registry entry's aliases. Unknown
    outlets fall through to the UNVERIFIED tier with unknown country/language,
    so nothing is silently trusted.
    """
    blob = (source_name or '').lower()
    for canonical, (tier, country, language, aliases) in constants.SOURCE_REGISTRY.items():
        if any(alias in blob for alias in aliases):
            return canonical, tier, country, language
    return None, constants.SOURCE_TIER_UNVERIFIED, None, None


def source_tier(source_name) -> str:
    """Quality tier for an outlet name (premium | quality | unverified)."""
    return source_meta(source_name)[1]


def is_verified(source_name) -> bool:
    """True when the outlet is a trusted (premium/quality) source."""
    return source_tier(source_name) in constants.VERIFIED_SOURCE_TIERS
