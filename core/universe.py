"""Asset universe loader (Phase 4).

The tracked universe is the committed, yfinance-validated list of the ~500
largest companies worldwide (``core/data/global_top500.csv``). Kept as a data
file rather than inline constants so it stays readable and easy to refresh.
Falls back to ``constants.DEFAULT_ASSETS`` if the file is missing.
"""
from __future__ import annotations

from pathlib import Path

from core import constants

UNIVERSE_FILE = Path(__file__).resolve().parent / 'data' / 'global_top500.csv'


def load_universe() -> list:
    """Return the asset universe as a list of {symbol, name, asset_type} dicts."""
    if not UNIVERSE_FILE.exists():
        return [dict(cfg) for cfg in constants.DEFAULT_ASSETS]

    universe = []
    for line in UNIVERSE_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        symbol, sep, name = line.partition('|')
        symbol, name = symbol.strip(), name.strip()
        if not symbol or not sep:
            continue
        universe.append({'symbol': symbol, 'name': name, 'asset_type': 'Stock'})
    return universe
