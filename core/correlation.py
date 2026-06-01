"""Sentiment ↔ forward-return correlation (Phase 2).

Measures whether news sentiment anticipates subsequent price moves, the core
measurement primitive behind the long-term self-calibration goal. Pure
pandas/numpy — Pearson via ``np.corrcoef`` and Spearman as Pearson of ranks,
so no scipy dependency is required. All functions are pure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import constants


def _pearson(x, y):
    """Pearson r, or None when undefined (too few points / zero variance)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < constants.CORRELATION_MIN_SAMPLES:
        return None
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return round(float(np.corrcoef(x, y)[0, 1]), 4)


def _spearman(x, y):
    """Spearman rho = Pearson of the rank-transformed inputs."""
    if len(x) < constants.CORRELATION_MIN_SAMPLES:
        return None
    xr = pd.Series(x).rank().to_numpy()
    yr = pd.Series(y).rank().to_numpy()
    return _pearson(xr, yr)


def _build_close_by_date(price_rows) -> pd.Series:
    """Collapse (timestamp, close) rows to one close per calendar date, sorted."""
    df = pd.DataFrame(list(price_rows), columns=['ts', 'close'])
    if df.empty:
        return pd.Series(dtype=float)
    df['date'] = pd.to_datetime(df['ts'], utc=True).dt.normalize()
    df['close'] = df['close'].astype(float)
    return df.groupby('date')['close'].last().sort_index()


def _forward_return(series, base_date, horizon_days, last_date):
    """Pct return from `base_date` to `base_date + horizon`, or None.

    Returns None when there is not yet enough forward data (the horizon target
    falls past the latest available price) — so recent news doesn't bias results.
    """
    target = base_date + pd.Timedelta(days=horizon_days)
    if target > last_date:
        return None
    base = series.asof(base_date)
    fut = series.asof(target)
    if base is None or fut is None or pd.isna(base) or pd.isna(fut) or base == 0:
        return None
    return (fut - base) / base


def compute_sentiment_correlation(news_items, price_rows,
                                  horizons=constants.CORRELATION_HORIZONS_DAYS) -> dict:
    """Correlate article sentiment with forward returns at each horizon.

    `news_items`: iterable of dict-likes with `timestamp` + `sentiment_score`.
    `price_rows`: iterable of (timestamp, close).
    Returns {sample_size, horizons:[{days, pearson, spearman, avg_return, n}]}.
    """
    series = _build_close_by_date(price_rows)
    scored = [n for n in news_items if n.get('sentiment_score') is not None]
    result = {'sample_size': len(scored), 'horizons': []}

    if series.empty or len(scored) < constants.CORRELATION_MIN_SAMPLES:
        result['horizons'] = [
            {'days': h, 'pearson': None, 'spearman': None, 'avg_return': None, 'n': 0}
            for h in horizons
        ]
        return result

    last_date = series.index.max()
    articles = [
        (pd.to_datetime(n['timestamp'], utc=True).normalize(), float(n['sentiment_score']))
        for n in scored
    ]

    for h in horizons:
        sentiments, returns = [], []
        for base_date, sentiment in articles:
            r = _forward_return(series, base_date, h, last_date)
            if r is None:
                continue
            sentiments.append(sentiment)
            returns.append(r)
        avg_return = round(float(np.mean(returns)) * 100, 4) if returns else None
        result['horizons'].append({
            'days': h,
            'pearson': _pearson(sentiments, returns),
            'spearman': _spearman(sentiments, returns),
            'avg_return': avg_return,  # mean forward return %, all sampled articles
            'n': len(returns),
        })
    return result
