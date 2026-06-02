"""Composite "Top Opportunità" ranking (Phase 4).

Blends four signals already produced elsewhere into a transparent 0–100
opportunity score per asset: news **sentiment** level, sentiment **momentum**
(improving vs. the prior window), a **technical** read (RSI/MACD), and **price
momentum**. Each component is normalized to [-1, 1], weighted (weights sum to
1.0 → raw score in [-1, 1]), then mapped to 0–100. Pure functions, no DB — the
caller assembles the per-asset inputs.

Not investment advice: a high score means "worth a look right now", not "buy".
"""
from __future__ import annotations

from core import constants


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _sentiment_component(sent_recent, n_articles):
    """Recent average sentiment (already -1..1), or neutral if too few articles."""
    if sent_recent is None or n_articles < constants.RANK_MIN_ARTICLES:
        return 0.0
    return _clip(float(sent_recent))


def _sentiment_momentum_component(sent_recent, sent_prior, n_articles):
    """How much sentiment improved vs. the prior window, clipped to [-1, 1]."""
    if (sent_recent is None or sent_prior is None
            or n_articles < constants.RANK_MIN_ARTICLES):
        return 0.0
    return _clip(float(sent_recent) - float(sent_prior))


def _technical_component(rsi, macd_hist):
    """Blend an RSI zone read with the MACD histogram sign into [-1, 1]."""
    parts = []
    if rsi is not None:
        if rsi >= constants.RANK_RSI_OVERBOUGHT:
            parts.append(-1.0)                       # overbought → risky
        elif rsi <= constants.RANK_RSI_OVERSOLD:
            parts.append(-0.7)                       # oversold / weak trend
        else:
            parts.append(_clip((float(rsi) - 50.0) / 20.0))  # 50→0, 70→+1, 30→-1
    if macd_hist is not None:
        parts.append(1.0 if macd_hist > 0 else (-1.0 if macd_hist < 0 else 0.0))
    if not parts:
        return 0.0
    return _clip(sum(parts) / len(parts))


def _momentum_component(price_return):
    """Recent price return (fraction) scaled so ±RANK_MOMENTUM_FULL_SCALE → ±1."""
    if price_return is None:
        return 0.0
    return _clip(float(price_return) / constants.RANK_MOMENTUM_FULL_SCALE)


def score_asset(inputs) -> dict:
    """Score a single asset's inputs dict → {score, components, low_news, ...}.

    `inputs` keys: symbol, name, sent_recent, sent_prior, n_articles, rsi,
    macd_hist, price_return (any may be None). Returns the score (0–100) plus
    the normalized components so the UI can explain *why*.
    """
    n_articles = inputs.get('n_articles') or 0
    s = _sentiment_component(inputs.get('sent_recent'), n_articles)
    ds = _sentiment_momentum_component(inputs.get('sent_recent'), inputs.get('sent_prior'), n_articles)
    t = _technical_component(inputs.get('rsi'), inputs.get('macd_hist'))
    m = _momentum_component(inputs.get('price_return'))

    raw = (constants.RANK_WEIGHT_SENTIMENT * s
           + constants.RANK_WEIGHT_SENTIMENT_MOMENTUM * ds
           + constants.RANK_WEIGHT_TECHNICAL * t
           + constants.RANK_WEIGHT_MOMENTUM * m)
    score = round((_clip(raw) + 1.0) / 2.0 * 100.0, 1)

    return {
        'symbol': inputs.get('symbol'),
        'name': inputs.get('name'),
        'score': score,
        'n_articles': n_articles,
        'low_news': n_articles < constants.RANK_MIN_ARTICLES,
        'components': {
            'sentiment': round(s, 3),
            'sentiment_momentum': round(ds, 3),
            'technical': round(t, 3),
            'momentum': round(m, 3),
        },
    }


def rank_assets(asset_inputs) -> list:
    """Score every asset and return them sorted best-first with a 1-based rank."""
    scored = [score_asset(a) for a in asset_inputs]
    scored.sort(key=lambda r: r['score'], reverse=True)
    for i, row in enumerate(scored, start=1):
        row['rank'] = i
    return scored
