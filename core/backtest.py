"""Sentiment-strategy backtesting engine (Phase 3).

A lightweight, pure pandas/numpy historical simulator for the "Strategy
Sandbox": a long-only rule set driven by rolling news sentiment with an
optional stop-loss. Computed entirely on read from stored prices + scored
news (no extra tables) — same pattern as ``indicators.py``/``correlation.py``.

Deliberately avoids Backtrader/PyAlgoTrade: those pull heavy deps and clash
with the numpy 2.x stack the project already pinned around (see ARCHITECTURE
§2). All functions are pure.

Execution model (close-to-close, no look-ahead): each calendar day carries the
trailing rolling-average sentiment computed from news up to and including that
day; signals act on that day's close. Long-only, all-in / all-out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import constants


# -- Series builders --------------------------------------------------------

def _build_close_by_date(price_rows) -> pd.Series:
    """Collapse (timestamp, close) rows to one close per calendar date, sorted."""
    df = pd.DataFrame(list(price_rows), columns=['ts', 'close'])
    if df.empty:
        return pd.Series(dtype=float)
    df['date'] = pd.to_datetime(df['ts'], utc=True).dt.normalize()
    df['close'] = df['close'].astype(float)
    return df.groupby('date')['close'].last().sort_index()


def _build_rolling_sentiment(news_items, dates, window_days) -> pd.Series:
    """Trailing mean daily-sentiment aligned to `dates`.

    Each day's value is the mean sentiment of all articles in the trailing
    `window_days` window (inclusive). Days with no article in the window carry
    NaN (treated as "no signal" by the simulator).
    """
    index = pd.DatetimeIndex(dates)
    scored = [n for n in news_items if n.get('sentiment_score') is not None]
    if not scored:
        return pd.Series(np.nan, index=index)

    df = pd.DataFrame({
        'date': [pd.to_datetime(n['timestamp'], utc=True).normalize() for n in scored],
        'score': [float(n['sentiment_score']) for n in scored],
    })
    daily = df.groupby('date')['score'].mean().sort_index()

    window = pd.Timedelta(days=window_days)
    values = []
    for d in index:
        mask = (daily.index > d - window) & (daily.index <= d)
        recent = daily[mask]
        values.append(float(recent.mean()) if len(recent) else np.nan)
    return pd.Series(values, index=index)


# -- Simulation -------------------------------------------------------------

def _simulate(closes: pd.Series, sentiment: pd.Series, *,
              buy_threshold, sell_threshold, stop_loss_pct, initial_capital):
    """Run the long-only rule set, returning (equity_series, trades, signals).

    Position is full-equity (all-in / all-out). Entry when flat and sentiment
    ≥ buy_threshold; exit when sentiment ≤ sell_threshold or close ≤ entry *
    (1 − stop_loss_pct). stop_loss_pct of 0 disables the stop.
    """
    cash = float(initial_capital)
    shares = 0.0
    entry_price = None
    entry_date = None
    trades, signals = [], []
    equity_values = []

    for date, close in closes.items():
        s = sentiment.get(date, np.nan)

        if shares == 0.0:
            if not np.isnan(s) and s >= buy_threshold:
                shares = cash / close
                cash = 0.0
                entry_price, entry_date = close, date
                signals.append({'date': _iso(date), 'type': 'buy', 'price': round(close, 4)})
        else:
            stop_hit = stop_loss_pct > 0 and close <= entry_price * (1 - stop_loss_pct)
            sentiment_exit = not np.isnan(s) and s <= sell_threshold
            if stop_hit or sentiment_exit:
                cash = shares * close
                reason = 'stop_loss' if stop_hit else 'sentiment'
                trades.append(_close_trade(entry_date, entry_price, date, close, reason))
                signals.append({'date': _iso(date), 'type': 'sell', 'price': round(close, 4)})
                shares = 0.0
                entry_price = entry_date = None

        equity_values.append(cash + shares * close)

    equity = pd.Series(equity_values, index=closes.index)

    # Mark-to-market any still-open position as an unrealized trade at the last close.
    if shares > 0.0:
        last_date, last_close = closes.index[-1], float(closes.iloc[-1])
        trades.append(_close_trade(entry_date, entry_price, last_date, last_close, 'open'))

    return equity, trades, signals


def _close_trade(entry_date, entry_price, exit_date, exit_price, reason) -> dict:
    ret = (exit_price - entry_price) / entry_price if entry_price else 0.0
    return {
        'entry_date': _iso(entry_date),
        'entry_price': round(float(entry_price), 4),
        'exit_date': _iso(exit_date),
        'exit_price': round(float(exit_price), 4),
        'return_pct': round(ret * 100, 4),
        'exit_reason': reason,
    }


# -- Metrics ----------------------------------------------------------------

def _metrics(equity: pd.Series, closes: pd.Series, trades, initial_capital) -> dict:
    """Risk/return metrics from the equity curve and closed trades."""
    final_equity = float(equity.iloc[-1])
    total_return = (final_equity / initial_capital - 1) if initial_capital else 0.0

    daily = equity.pct_change().dropna().to_numpy()
    rf_daily = constants.BACKTEST_RISK_FREE_RATE / constants.BACKTEST_TRADING_DAYS_PER_YEAR
    ann = np.sqrt(constants.BACKTEST_TRADING_DAYS_PER_YEAR)

    sharpe = _sharpe(daily, rf_daily, ann)
    sortino = _sortino(daily, rf_daily, ann)
    max_dd = _max_drawdown(equity)

    closed = [t for t in trades if t['exit_reason'] != 'open']
    wins = [t for t in closed if t['return_pct'] > 0]
    win_rate = (len(wins) / len(closed) * 100) if closed else None

    first_close = float(closes.iloc[0])
    last_close = float(closes.iloc[-1])
    buy_hold = (last_close / first_close - 1) if first_close else 0.0

    return {
        'initial_capital': round(initial_capital, 2),
        'final_equity': round(final_equity, 2),
        'total_return_pct': round(total_return * 100, 4) + 0.0,  # normalize -0.0 → 0.0
        'buy_hold_return_pct': round(buy_hold * 100, 4),
        'alpha_pct': round((total_return - buy_hold) * 100, 4),
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'max_drawdown_pct': max_dd,
        'win_rate_pct': round(win_rate, 2) if win_rate is not None else None,
        'num_trades': len(closed),
    }


# Daily returns below this magnitude are floating-point noise (e.g. a single
# all-in buy makes shares*close ≈ but not exactly the cash spent), not real
# P&L — a flat equity curve must report N/D, never a spurious ratio.
_FLAT_EPS = 1e-9


def _is_flat(daily) -> bool:
    return len(daily) < 2 or np.max(np.abs(daily)) < _FLAT_EPS


def _sharpe(daily, rf_daily, ann):
    if _is_flat(daily) or np.std(daily, ddof=1) < _FLAT_EPS:
        return None
    excess = daily - rf_daily
    return round(float(np.mean(excess) / np.std(daily, ddof=1) * ann), 4)


def _sortino(daily, rf_daily, ann):
    if _is_flat(daily):
        return None
    excess = daily - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 2 or np.std(downside, ddof=1) < _FLAT_EPS:
        return None
    return round(float(np.mean(excess) / np.std(downside, ddof=1) * ann), 4)


def _max_drawdown(equity: pd.Series):
    """Largest peak-to-trough decline as a negative percentage."""
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return round(float(drawdown.min()) * 100, 4)


# -- Helpers ----------------------------------------------------------------

def _iso(date) -> str:
    return pd.Timestamp(date).strftime('%Y-%m-%d')


def _empty_result(params) -> dict:
    return {
        'params': params,
        'metrics': None,
        'equity_curve': [],
        'trades': [],
        'signals': [],
        'insufficient_data': True,
    }


# -- Public entry point -----------------------------------------------------

def run_backtest(price_rows, news_items, *,
                 buy_threshold=constants.BACKTEST_BUY_THRESHOLD,
                 sell_threshold=constants.BACKTEST_SELL_THRESHOLD,
                 stop_loss_pct=constants.BACKTEST_STOP_LOSS_PCT,
                 sentiment_window_days=constants.BACKTEST_SENTIMENT_WINDOW_DAYS,
                 initial_capital=constants.BACKTEST_INITIAL_CAPITAL) -> dict:
    """Backtest the sentiment sandbox strategy over the stored history.

    `price_rows`: iterable of (timestamp, close). `news_items`: iterable of
    dict-likes with `timestamp` + `sentiment_score`. Returns a chart-ready dict
    with `params`, `metrics`, `equity_curve`, `trades`, and `signals`.
    """
    params = {
        'buy_threshold': buy_threshold,
        'sell_threshold': sell_threshold,
        'stop_loss_pct': stop_loss_pct,
        'sentiment_window_days': sentiment_window_days,
        'initial_capital': initial_capital,
    }

    closes = _build_close_by_date(price_rows)
    if len(closes) < constants.BACKTEST_MIN_DAYS:
        return _empty_result(params)

    sentiment = _build_rolling_sentiment(news_items, closes.index, sentiment_window_days)
    equity, trades, signals = _simulate(
        closes, sentiment,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        stop_loss_pct=stop_loss_pct,
        initial_capital=initial_capital,
    )

    return {
        'params': params,
        'metrics': _metrics(equity, closes, trades, initial_capital),
        'equity_curve': [
            {'date': _iso(d), 'equity': round(float(v), 2)} for d, v in equity.items()
        ],
        'trades': trades,
        'signals': signals,
        'insufficient_data': False,
    }
