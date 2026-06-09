"""Paper-trading decision engine (Phase 5).

The forward-in-time twin of the Phase 3 backtester: instead of replaying the
whole history, it answers "given where this asset stands *right now*, should the
virtual portfolio act?". Same long-only, rolling-sentiment rule set (enter when
sentiment is strong, exit on a sentiment reversal or a stop-loss) so paper
results stay comparable to a backtest of the same thresholds.

Pure functions, no DB and no clock of their own (the caller passes `as_of`): the
DB orchestration lives in ``tasks.run_paper_trading`` per the project convention
(thin tasks, reusable helpers). Money is play money tracked as floats.
"""
from __future__ import annotations

import pandas as pd

from core import constants


def rolling_sentiment(news_items, window_days, as_of):
    """Mean sentiment of articles in the trailing ``window_days`` ending at ``as_of``.

    ``news_items``: iterable of dict-likes with ``timestamp`` + ``sentiment_score``.
    Returns the mean score (-1..1) over ``(as_of - window_days, as_of]`` or
    ``None`` when no scored article falls in the window (→ "no signal").
    """
    cutoff = pd.to_datetime(as_of, utc=True) - pd.Timedelta(days=window_days)
    as_of_ts = pd.to_datetime(as_of, utc=True)

    scores = []
    for n in news_items:
        score = n.get('sentiment_score')
        if score is None:
            continue
        ts = pd.to_datetime(n['timestamp'], utc=True)
        if cutoff < ts <= as_of_ts:
            scores.append(float(score))

    if not scores:
        return None
    return sum(scores) / len(scores)


def latest_signal(latest_close, sentiment, *, holding, entry_price,
                  buy_threshold=constants.PAPER_BUY_THRESHOLD,
                  sell_threshold=constants.PAPER_SELL_THRESHOLD,
                  stop_loss_pct=constants.PAPER_STOP_LOSS_PCT):
    """Decide the action for one asset → ``(action, reason)``.

    ``action`` is ``'buy'``, ``'sell'`` or ``None``; ``reason`` explains a trade
    (``'sentiment'`` or ``'stop_loss'``) or is ``None`` when holding steady.

    - Flat: buy when sentiment is known and ≥ ``buy_threshold``.
    - Holding: sell when the stop-loss trips (close ≤ entry·(1−stop)) or sentiment
      reverses (≤ ``sell_threshold``); the stop takes priority. A stop check needs
      only the price, so a held position can still be protected with no fresh news.
    """
    if latest_close is None or latest_close <= 0:
        return None, None

    if not holding:
        if sentiment is not None and sentiment >= buy_threshold:
            return 'buy', 'sentiment'
        return None, None

    stop_hit = (stop_loss_pct > 0 and entry_price
                and latest_close <= entry_price * (1 - stop_loss_pct))
    if stop_hit:
        return 'sell', 'stop_loss'
    if sentiment is not None and sentiment <= sell_threshold:
        return 'sell', 'sentiment'
    return None, None


# The execution-cost model is shared with the backtester; re-exported here so the
# paper engine's public surface (``paper_trading.execution_price`` / ``.commission``)
# stays stable for callers and tests.
from core.execution import commission, execution_price  # noqa: E402,F401


def position_size(total_equity, cash, fill_price, n_open_positions, *,
                  max_positions=constants.PAPER_MAX_POSITIONS,
                  fraction=constants.PAPER_POSITION_FRACTION,
                  min_trade_value=constants.PAPER_MIN_TRADE_VALUE,
                  commission_pct=constants.PAPER_COMMISSION_PCT):
    """Quantity to buy for a new position, or ``0.0`` when a buy is not warranted.

    Targets ``fraction`` of total equity, capped by the cash budget, refused once
    the diversification cap (``max_positions``) is reached or the budget would be
    dust (< ``min_trade_value``). ``fill_price`` is the post-slippage price we
    actually pay; the all-in cost per share includes commission so the resulting
    quantity never overdraws cash. Pure sizing — never mutates state.
    """
    if fill_price is None or fill_price <= 0:
        return 0.0
    if n_open_positions >= max_positions:
        return 0.0

    target_value = total_equity * fraction
    budget = min(target_value, cash)
    if budget < min_trade_value:
        return 0.0
    cost_per_share = fill_price * (1 + commission_pct)
    return budget / cost_per_share
