"""Shared risk/return metrics for equity curves.

Extracted so the Phase 3 backtester and the Phase 5 paper portfolio report the
*same* Sharpe / Sortino / drawdown / win-rate numbers — a backtest of a strategy
and the live paper run of it stay directly comparable. Pure ``numpy``/``pandas``
math, no DB and no clock; callers pass already-fetched values.

The annualization assumes one return observation per trading day (the backtest
works on daily bars; the paper portfolio snapshots roughly once per daily cycle),
scaling by ``sqrt(252)`` per the standard convention.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import constants

# Returns below this magnitude are floating-point noise (e.g. a single all-in
# buy makes shares*close ≈ but not exactly the cash spent), not real P&L — a flat
# equity curve must report N/D, never a spurious ratio.
FLAT_EPS = 1e-9


def risk_free_daily() -> float:
    """The annual risk-free rate expressed per trading day."""
    return constants.BACKTEST_RISK_FREE_RATE / constants.BACKTEST_TRADING_DAYS_PER_YEAR


def annualization() -> float:
    """Scale factor turning per-period stats into annualized ones (``sqrt(252)``)."""
    return float(np.sqrt(constants.BACKTEST_TRADING_DAYS_PER_YEAR))


def is_flat(daily) -> bool:
    """True when there's too little movement to compute a meaningful ratio."""
    return len(daily) < 2 or np.max(np.abs(daily)) < FLAT_EPS


def sharpe(daily, rf_daily, ann):
    """Annualized Sharpe ratio, or ``None`` when the curve is flat/degenerate."""
    if is_flat(daily) or np.std(daily, ddof=1) < FLAT_EPS:
        return None
    excess = daily - rf_daily
    return round(float(np.mean(excess) / np.std(daily, ddof=1) * ann), 4)


def sortino(daily, rf_daily, ann):
    """Annualized Sortino ratio (downside-only deviation), or ``None`` if flat."""
    if is_flat(daily):
        return None
    excess = daily - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 2 or np.std(downside, ddof=1) < FLAT_EPS:
        return None
    return round(float(np.mean(excess) / np.std(downside, ddof=1) * ann), 4)


def max_drawdown(equity: pd.Series):
    """Largest peak-to-trough decline of the equity curve, as a negative %."""
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return round(float(drawdown.min()) * 100, 4)


def equity_curve_metrics(values) -> dict | None:
    """Sharpe / Sortino / max-drawdown from a chronological sequence of equity values.

    ``values``: floats in time order (e.g. ``PortfolioSnapshot.total_value``).
    Returns ``None`` when there are fewer than two points; individual ratios are
    ``None`` when the curve is too flat to be meaningful.
    """
    if values is None or len(values) < 2:
        return None
    equity = pd.Series([float(v) for v in values])
    daily = equity.pct_change().dropna().to_numpy()
    rf, ann = risk_free_daily(), annualization()
    return {
        'sharpe_ratio': sharpe(daily, rf, ann),
        'sortino_ratio': sortino(daily, rf, ann),
        'max_drawdown_pct': max_drawdown(equity),
    }


def win_rate(realized_pnls) -> float | None:
    """Percentage of closed trades that made money, or ``None`` when none closed."""
    closed = [p for p in realized_pnls if p is not None]
    if not closed:
        return None
    wins = sum(1 for p in closed if p > 0)
    return round(wins / len(closed) * 100, 2)


def buy_hold_return_pct(pairs) -> float | None:
    """Equal-weight buy-&-hold return % across ``(first_price, last_price)`` pairs.

    The fair "what if you'd just held the same names" benchmark for a stock-picker:
    average the simple return of each symbol over the portfolio's lifetime. Skips
    pairs with a missing/zero start price; ``None`` when nothing is usable.
    """
    rets = [(float(last) / float(first) - 1) for first, last in pairs
            if first and last is not None and float(first) > 0]
    if not rets:
        return None
    return round(sum(rets) / len(rets) * 100, 4)
