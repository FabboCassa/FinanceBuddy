"""Entity linking — attribute an article to tracked assets (Phase 4 NER).

For a known, small asset universe, dictionary entity-linking is more reliable
than generic NER: build a per-asset alias set (symbol + cleaned company name +
curated extras) and whole-word match it against the article text. General RSS
feeds carry no ticker, so this is what binds each item to the right asset.

Pure functions, no DB. A model-based NER (spaCy / dslim-bert-NER) can be layered
on later for unknown organizations — same cold-start-then-upgrade pattern as the
relevance filter.
"""
from __future__ import annotations

import re

from core import constants


def _strip_company_suffixes(name: str) -> str:
    """Drop legal/exchange suffixes so 'Apple Inc.' → 'apple'."""
    tokens = re.split(r'[\s,]+', name)
    kept = [t for t in tokens if t.lower().strip('.') not in constants.COMPANY_NAME_SUFFIXES]
    return ' '.join(kept).strip()


def build_alias_map(assets) -> dict:
    """Build {symbol: [aliases]} from an iterable of (symbol, name).

    Aliases are lowercased and de-duplicated: the symbol, its exchange-stripped
    base (``SWDA.MI`` → ``swda``), the company name, the name without legal
    suffixes, and any curated ``constants.ASSET_ALIASES`` entries. Aliases
    shorter than ``NER_MIN_ALIAS_LEN`` are dropped as too ambiguous.
    """
    alias_map = {}
    for symbol, name in assets:
        aliases = {symbol.lower(), symbol.split('.')[0].lower()}
        if name:
            aliases.add(name.lower())
            cleaned = _strip_company_suffixes(name).lower()
            if cleaned:
                aliases.add(cleaned)
        aliases.update(a.lower() for a in constants.ASSET_ALIASES.get(symbol, ()))
        alias_map[symbol] = sorted(a for a in aliases if len(a) >= constants.NER_MIN_ALIAS_LEN)
    return alias_map


def match_symbols(text, alias_map) -> set:
    """Return the set of symbols whose aliases occur as whole words in `text`."""
    if not text:
        return set()
    blob = text.lower()
    matched = set()
    for symbol, aliases in alias_map.items():
        for alias in aliases:
            if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', blob):
                matched.add(symbol)
                break
    return matched
