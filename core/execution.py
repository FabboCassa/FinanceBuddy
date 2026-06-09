"""Shared trade-execution cost model (Phase 3 backtest + Phase 5 paper).

A frictionless fill flatters a strategy; these pure helpers make every simulated
trade pay what a real one would — adverse slippage on the fill price plus a flat
commission on the gross value. Kept strategy-agnostic and in one place so the
backtester and the live paper trader charge identical costs and stay comparable.

Pure functions, no DB and no clock.
"""
from __future__ import annotations

from core import constants


def execution_price(reference_price, side, slippage_pct=constants.TRADING_SLIPPAGE_PCT):
    """Adverse fill price vs. the observed close → what we actually transact at.

    A ``'buy'`` pays slightly up, a ``'sell'`` receives slightly less; this models
    the bid/ask spread and market impact a real order would suffer.
    """
    factor = (1 + slippage_pct) if side == 'buy' else (1 - slippage_pct)
    return reference_price * factor


def commission(gross_value, commission_pct=constants.TRADING_COMMISSION_PCT):
    """Flat percentage fee on a trade's gross value (charged on each side)."""
    return abs(gross_value) * commission_pct
