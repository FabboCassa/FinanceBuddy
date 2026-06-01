"""Technical-analysis indicators (Phase 2).

Pure-pandas implementations of EMA, RSI (Wilder) and MACD. Kept dependency-free
beyond pandas (already pulled in by yfinance) because pandas-ta is incompatible
with numpy 2.x. Functions are pure: they take/return pandas objects and never
mutate their inputs.
"""
from __future__ import annotations

import pandas as pd

from core import constants


def ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential moving average over `period` (adjust=False = recursive EMA)."""
    return close.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = constants.RSI_PERIOD) -> pd.Series:
    """Wilder's Relative Strength Index in the 0..100 range."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing == EMA with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series,
         fast: int = constants.MACD_FAST,
         slow: int = constants.MACD_SLOW,
         signal: int = constants.MACD_SIGNAL) -> pd.DataFrame:
    """MACD line, signal line and histogram as a 3-column DataFrame."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({
        'macd': macd_line,
        'macd_signal': signal_line,
        'macd_hist': macd_line - signal_line,
    })


def _to_points(series: pd.Series, epochs: list[int]) -> list[dict]:
    """Zip a value series with epoch seconds, dropping NaN points (chart-ready)."""
    points = []
    for epoch, value in zip(epochs, series.tolist()):
        if value is None or pd.isna(value):
            continue
        points.append({'time': epoch, 'value': round(float(value), 4)})
    return points


def compute_indicators(timestamps, closes) -> dict:
    """Compute all indicators for aligned `timestamps` + `closes` iterables.

    Returns a dict of chart-ready series keyed by indicator name. EMA series are
    keyed `ema20`/`ema50`/... Each series is a list of {time, value} with NaN
    warm-up points removed.
    """
    epochs = [int(ts.timestamp()) for ts in timestamps]
    close = pd.Series([float(c) for c in closes], dtype='float64')

    result: dict[str, list] = {}
    for period in constants.EMA_PERIODS:
        result[f'ema{period}'] = _to_points(ema(close, period), epochs)

    result['rsi'] = _to_points(rsi(close), epochs)

    macd_df = macd(close)
    result['macd'] = _to_points(macd_df['macd'], epochs)
    result['macd_signal'] = _to_points(macd_df['macd_signal'], epochs)
    result['macd_hist'] = _to_points(macd_df['macd_hist'], epochs)
    return result
