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

from core import constants, execution, metrics


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
              buy_threshold, sell_threshold, stop_loss_pct, initial_capital,
              commission_pct=constants.TRADING_COMMISSION_PCT,
              slippage_pct=constants.TRADING_SLIPPAGE_PCT):
    """Run the long-only rule set, returning (equity_series, trades, signals).

    Position is full-equity (all-in / all-out). Entry when flat and sentiment
    ≥ buy_threshold; exit when sentiment ≤ sell_threshold or close ≤ entry *
    (1 − stop_loss_pct). stop_loss_pct of 0 disables the stop.

    Fills carry the shared execution costs (slippage + commission, see
    core/execution.py) so the equity curve matches what the paper trader would do.
    The stop-loss still triggers off the raw close (the market level), not the fill.
    """
    cash = float(initial_capital)
    shares = 0.0
    entry_price = None  # slippage-adjusted buy fill (the cost basis)
    entry_date = None
    trades, signals = [], []
    equity_values = []

    for date, close in closes.items():
        s = sentiment.get(date, np.nan)

        if shares == 0.0:
            if not np.isnan(s) and s >= buy_threshold:
                fill = execution.execution_price(close, 'buy', slippage_pct)
                # All-in: shares·fill + commission(shares·fill) consumes all cash.
                shares = cash / (fill * (1 + commission_pct))
                cash = 0.0
                entry_price, entry_date = fill, date
                signals.append({'date': _iso(date), 'type': 'buy', 'price': round(fill, 4)})
        else:
            stop_hit = stop_loss_pct > 0 and close <= entry_price * (1 - stop_loss_pct)
            sentiment_exit = not np.isnan(s) and s <= sell_threshold
            if stop_hit or sentiment_exit:
                fill = execution.execution_price(close, 'sell', slippage_pct)
                gross = shares * fill
                cash = gross - execution.commission(gross, commission_pct)
                reason = 'stop_loss' if stop_hit else 'sentiment'
                trades.append(_close_trade(entry_date, entry_price, date, fill, reason,
                                           commission_pct))
                signals.append({'date': _iso(date), 'type': 'sell', 'price': round(fill, 4)})
                shares = 0.0
                entry_price = entry_date = None

        equity_values.append(cash + shares * close)

    equity = pd.Series(equity_values, index=closes.index)

    # Mark-to-market any still-open position as an unrealized trade at the last close.
    if shares > 0.0:
        last_date, last_close = closes.index[-1], float(closes.iloc[-1])
        trades.append(_close_trade(entry_date, entry_price, last_date, last_close, 'open',
                                   commission_pct))

    return equity, trades, signals


def _close_trade(entry_date, entry_price, exit_date, exit_price, reason,
                 commission_pct=constants.TRADING_COMMISSION_PCT) -> dict:
    """Build a trade record. ``return_pct`` is the net round-trip return: the
    move from the all-in entry cost to the net exit proceeds. An ``'open'`` trade
    is marked at the raw close (no exit yet) but still bears its entry commission."""
    allin_entry = entry_price * (1 + commission_pct)
    net_exit = (exit_price * (1 - commission_pct) if reason != 'open' else exit_price)
    ret = (net_exit - allin_entry) / allin_entry if entry_price else 0.0
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
    rf_daily = metrics.risk_free_daily()
    ann = metrics.annualization()

    sharpe = metrics.sharpe(daily, rf_daily, ann)
    sortino = metrics.sortino(daily, rf_daily, ann)
    max_dd = metrics.max_drawdown(equity)

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
                 initial_capital=constants.BACKTEST_INITIAL_CAPITAL,
                 commission_pct=constants.TRADING_COMMISSION_PCT,
                 slippage_pct=constants.TRADING_SLIPPAGE_PCT) -> dict:
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
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
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


# -- Grid search ("Ottimizza") ------------------------------------------------

def _summary_metrics(result) -> dict:
    """Compact metric tile for one grid cell (full result is too heavy)."""
    m = result['metrics']
    return {
        'total_return_pct': m['total_return_pct'],
        'alpha_pct': m['alpha_pct'],
        'sharpe_ratio': m['sharpe_ratio'],
        'max_drawdown_pct': m['max_drawdown_pct'],
        'win_rate_pct': m['win_rate_pct'],
        'num_trades': m['num_trades'],
    }


def grid_search(price_rows, news_items, *,
                buy_thresholds=constants.BACKTEST_GRID_BUY_THRESHOLDS,
                sell_thresholds=constants.BACKTEST_GRID_SELL_THRESHOLDS,
                stop_losses=constants.BACKTEST_GRID_STOP_LOSSES,
                windows=constants.BACKTEST_GRID_WINDOWS,
                train_fraction=constants.BACKTEST_GRID_TRAIN_FRACTION,
                top_n=constants.BACKTEST_GRID_TOP_N,
                initial_capital=constants.BACKTEST_INITIAL_CAPITAL) -> dict:
    """Try every parameter combination with a train/test split (anti-overfit).

    Prices are split chronologically: the first `train_fraction` of days is the
    TRAIN segment, the rest is TEST. Combinations are ranked by **train Sharpe**
    but each result also carries its TEST metrics — a combo that shines in
    train and collapses in test was just memorising the past. News are passed
    whole to both segments: the rolling sentiment is trailing-only, so this
    leaks nothing from the future.
    """
    rows = sorted(list(price_rows), key=lambda r: r[0])
    split = int(len(rows) * train_fraction)
    train_rows, test_rows = rows[:split], rows[split:]
    news = list(news_items)

    combos = [
        dict(buy_threshold=b, sell_threshold=s, stop_loss_pct=sl,
             sentiment_window_days=w)
        for b in buy_thresholds for s in sell_thresholds
        for sl in stop_losses for w in windows
        if s < b  # an exit threshold at/above the entry threshold is nonsense
    ][:constants.BACKTEST_GRID_MAX_COMBOS]

    results, tested = [], 0
    for combo in combos:
        train = run_backtest(train_rows, news, initial_capital=initial_capital, **combo)
        if train['insufficient_data'] or train['metrics'] is None:
            continue
        tested += 1
        test = run_backtest(test_rows, news, initial_capital=initial_capital, **combo)
        results.append({
            'params': combo,
            'train': _summary_metrics(train),
            'test': (_summary_metrics(test)
                     if not test['insufficient_data'] else None),
        })

    results.sort(
        key=lambda r: (r['train']['sharpe_ratio'] is not None,
                       r['train']['sharpe_ratio'] or 0.0),
        reverse=True,
    )

    return {
        'combos_tested': tested,
        'train_days': len(_build_close_by_date(train_rows)),
        'test_days': len(_build_close_by_date(test_rows)),
        'split_date': _iso(rows[split][0]) if rows and 0 < split < len(rows) else None,
        'results': results[:top_n],
        'insufficient_data': tested == 0,
    }
