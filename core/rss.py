"""RSS ingestion for quality news outlets (Phase 4).

Quality newspapers publish general-interest feeds (not per-ticker), so each
entry is attributed to tracked assets downstream via the entity linker
(``entities.match_symbols``); the source tier/country/language carry over from
the curated ``SOURCE_REGISTRY``. ``feedparser`` is imported lazily so this
module loads without the dependency present and unit tests can mock the parse.
"""
from __future__ import annotations

import calendar
import datetime
import logging

logger = logging.getLogger(__name__)


def parse_feed(url):
    """Fetch + parse a feed URL (thin wrapper; mocked in tests)."""
    import feedparser
    return feedparser.parse(url)


def _entry_timestamp(entry):
    """Best-effort aware UTC datetime from a feed entry, or None."""
    for key in ('published_parsed', 'updated_parsed'):
        struct = entry.get(key)
        if struct:
            return datetime.datetime.fromtimestamp(calendar.timegm(struct), tz=datetime.timezone.utc)
    return None


def normalize_entry(entry, default_source):
    """Map one feed entry to the common news-field dict, or None if unusable.

    `entry` is a dict-like (feedparser entry). The per-entry `source` title (when
    present) wins over the feed-level `default_source`, so syndicated items keep
    their real outlet for tier resolution.
    """
    title = entry.get('title')
    link = entry.get('link')
    if not title or not link:
        return None

    timestamp = _entry_timestamp(entry)
    if timestamp is None:
        return None

    source_obj = entry.get('source') or {}
    source = source_obj.get('title') if isinstance(source_obj, dict) else None
    summary = entry.get('summary', '') or ''
    return {
        'title': title,
        'url': link,
        'source': source or default_source,
        'timestamp': timestamp,
        'summary': summary,
    }
