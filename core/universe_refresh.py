"""Refresh the tracked universe from a live market-cap ranking (Phase 4+).

The committed ``global_top500.csv`` is a point-in-time snapshot; on its own it
never picks up newly-listed companies or names that grew into the top ranks.
This module pulls the current top-N by market cap from companiesmarketcap.com
(the same source the CSV came from) and diffs it against the tracked assets so
the ``refresh_universe`` task can seed the newcomers. Names that fall out of the
top-N are reported, never deleted — their price/news history is kept.

Design: the network fetch is thin; the two decision helpers
(:func:`parse_marketcap_symbols`, :func:`diff_universe`) are pure and
unit-tested. Tickers are read from the per-row logo filename
(``…/company-logos/64/NVDA.png``) — a stable anchor that already carries
yfinance-style suffixes (``2222.SR``, ``9988.HK``, ``005930.KS``).
"""
from __future__ import annotations

import logging
import re

from core import constants

logger = logging.getLogger(__name__)

# Ticker sits in the logo image path: .../company-logos/<size>/<TICKER>.<ext>
_LOGO_TICKER_RE = re.compile(
    r'company-logos/[^/"\']+/([A-Za-z0-9.\-]+)\.(?:png|webp|svg|jpg|jpeg)',
    re.IGNORECASE,
)


def parse_marketcap_symbols(html: str) -> list:
    """Ordered, de-duplicated ticker list from one ranking page's raw HTML.

    Preserves first (highest-rank) occurrence; ignores anything that isn't a
    company logo (nav/flag/icon images don't match the company-logos path).
    """
    out, seen = [], set()
    for match in _LOGO_TICKER_RE.finditer(html or ''):
        symbol = match.group(1)
        # Each row ships a light AND a dark logo; the dark one is named
        # <TICKER>.D.png. Collapse the ".D" dark-mode suffix so we emit the real
        # ticker ("AAPL") and not a bogus "AAPL.D" that fails yfinance.
        if symbol.endswith('.D'):
            symbol = symbol[:-2]
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def diff_universe(ranked_symbols, tracked_symbols):
    """Split a fresh ranking against the tracked set.

    Returns ``(new, dropped)``:
      * ``new``     — in the ranking but not yet tracked (ranking order kept, so
                      the biggest newcomers are seeded first).
      * ``dropped`` — tracked but no longer in the ranking (candidates to retire;
                      the caller reports them rather than deleting).
    """
    tracked = set(tracked_symbols)
    ranked_set = set(ranked_symbols)
    new = [s for s in ranked_symbols if s not in tracked]
    dropped = [s for s in tracked_symbols if s not in ranked_set]
    return new, dropped


def fetch_top_marketcap_symbols(top_n=None, session=None):
    """Live top-N tickers by market cap (paged fetch from the source site).

    ``session`` is any object with a ``requests``-style ``.get`` (injected in
    tests). Degrades gracefully: a failed/empty page stops paging and returns
    whatever was gathered so far (an empty list tells the caller to skip).
    """
    import requests

    top_n = top_n or constants.UNIVERSE_TARGET_SIZE
    session = session or requests
    headers = {'User-Agent': constants.UNIVERSE_SOURCE_USER_AGENT}

    symbols = []
    for page in range(1, constants.UNIVERSE_SOURCE_MAX_PAGES + 1):
        url = constants.UNIVERSE_SOURCE_URL.format(page=page)
        try:
            resp = session.get(url, headers=headers,
                               timeout=constants.UNIVERSE_SOURCE_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:  # network / HTTP error → stop, keep what we have
            logger.warning("Universe source page %s failed: %s", page, exc)
            break
        page_symbols = parse_marketcap_symbols(resp.text)
        if not page_symbols:
            break
        symbols.extend(page_symbols)
        if len(symbols) >= top_n:
            break

    # De-dupe across pages preserving order, cap at top_n.
    seen, ordered = set(), []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
        if len(ordered) >= top_n:
            break
    return ordered


def validate_and_name(symbol):
    """(is_valid, name) for a candidate ticker: resolves on yfinance with data.

    Guards the universe against dead/unlisted tickers (the reason the seed CSV
    was yfinance-validated) so a refresh never adds a symbol that would just spam
    "possibly delisted". Name falls back to the symbol if yfinance has none.
    """
    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=constants.FALLBACK_PRICE_PERIOD,
                              interval=constants.FALLBACK_PRICE_INTERVAL)
        if hist is None or getattr(hist, 'empty', True):
            return False, None
        name = symbol
        try:
            info = ticker.info or {}
            name = info.get('shortName') or info.get('longName') or symbol
        except Exception:  # .info is flaky/rate-limited - the name is optional
            pass
        return True, name
    except Exception as exc:
        logger.warning("Universe validate failed for %s: %s", symbol, exc)
        return False, None


def refresh_universe_members(top_n=None, backfill=True):
    """Add newly-large / newly-listed companies to the tracked universe.

    Pulls the live top-N by market cap, diffs against tracked assets, validates
    each newcomer on yfinance, seeds the valid ones (idempotent get_or_create)
    and deep-backfills their history. Names that fell out of the top-N are
    reported, not deleted (their price/news history is preserved).
    """
    from core.models import Asset
    from core.tasks import fetch_prices_batched  # lazy: avoid import cycle

    top_n = top_n or constants.UNIVERSE_TARGET_SIZE
    ranked = fetch_top_marketcap_symbols(top_n)
    if not ranked:
        logger.warning("Universe refresh: source returned no symbols; skipping.")
        return {'added': 0, 'invalid': 0, 'dropped': 0,
                'added_symbols': [], 'dropped_symbols': []}

    tracked = list(Asset.objects.values_list('symbol', flat=True))
    new, dropped = diff_universe(ranked, tracked)

    added, invalid = [], []
    for symbol in new:
        ok, name = validate_and_name(symbol)
        if not ok:
            invalid.append(symbol)
            continue
        Asset.objects.get_or_create(
            symbol=symbol, defaults={'name': name, 'asset_type': 'Stock'})
        added.append(symbol)

    if backfill and added:
        try:
            fetch_prices_batched(
                Asset.objects.filter(symbol__in=added),
                period=constants.BOOTSTRAP_PRICE_PERIOD,
                interval=constants.BOOTSTRAP_PRICE_INTERVAL,
            )
        except Exception as exc:
            logger.error("Universe refresh: history backfill failed: %s", exc)

    preview = ", ".join(dropped[:20]) + ("..." if len(dropped) > 20 else "")
    logger.info(
        "Universe refresh: +%d added, %d invalid skipped, %d dropped out of "
        "top-%d (kept, not deleted): %s",
        len(added), len(invalid), len(dropped), top_n, preview,
    )
    return {'added': len(added), 'invalid': len(invalid), 'dropped': len(dropped),
            'added_symbols': added, 'dropped_symbols': dropped}
