"""News relevance & forward-impact (Phase 4, cold-start).

First rung of the self-calibrating relevance filter: assign each article a
theme category by keyword voting (cold-start, no training) and record its
forward price impact at 1/3/7-day horizons. The forward impact is the
supervision signal a later self-supervised classifier learns from — the system
is meant to *learn* what matters from market reaction, so this module only
bootstraps the loop; it never hard-codes the final verdict.

Pure functions, no DB. Forward returns reuse the ``correlation`` primitives so
the per-article impact and the aggregate correlation matrix stay consistent.
"""
from __future__ import annotations

import pandas as pd

from core import constants
from core.correlation import _build_close_by_date, _forward_return


def categorize(title, text='') -> str:
    """Return the best-matching theme category for an article (cold-start).

    Counts keyword hits per theme over the lowercased title+text; the theme with
    the most hits wins. Noise keywords compete too — if noise scores highest the
    article is flagged as noise. No keyword hit at all → uncategorized (unknown,
    deferred to later NLP stages rather than guessed).
    """
    blob = f"{title or ''} {text or ''}".lower()

    scores = {
        category: sum(1 for kw in keywords if kw in blob)
        for category, keywords in constants.NEWS_CATEGORY_KEYWORDS.items()
    }
    noise_score = sum(1 for kw in constants.NEWS_NOISE_KEYWORDS if kw in blob)

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    if best_score == 0 and noise_score == 0:
        return constants.NEWS_CATEGORY_UNCATEGORIZED
    if noise_score > best_score:
        return constants.NEWS_CATEGORY_NOISE
    return best_category


def category_from_nli(top_label, top_score, threshold=constants.NLI_MIN_CONFIDENCE) -> str:
    """Decode a zero-shot top (label, score) into a category key.

    Below `threshold` the verdict isn't trusted → uncategorized, the same
    conservative stance as the keyword path (never assert what can't be
    justified). Unknown labels also fall through to uncategorized.
    """
    if top_score is None or top_score < threshold:
        return constants.NEWS_CATEGORY_UNCATEGORIZED
    return constants.NLI_HYPOTHESIS_TO_CATEGORY.get(top_label, constants.NEWS_CATEGORY_UNCATEGORIZED)


def is_relevant(category):
    """Tri-state relevance: True for a signal theme, False for noise, else None.

    Uncategorized stays None (unknown) on purpose — the cold-start filter must
    not assert irrelevance it cannot justify; later stages resolve it.
    """
    if category in constants.RELEVANT_NEWS_CATEGORIES:
        return True
    if category == constants.NEWS_CATEGORY_NOISE:
        return False
    return None


def compute_forward_impact(timestamp, price_rows,
                           horizons=constants.FORWARD_IMPACT_HORIZONS_DAYS):
    """Forward % return from the article date at each horizon.

    Returns ``{str(days): pct_or_None}`` (None for horizons whose target date is
    past the latest available close, so values mature as history accumulates —
    same no-look-ahead rule as the correlation matrix). Returns None entirely
    when there is no usable price series.
    """
    series = _build_close_by_date(price_rows)
    if series.empty:
        return None

    base_date = pd.to_datetime(timestamp, utc=True).normalize()
    last_date = series.index.max()
    impact = {}
    for h in horizons:
        r = _forward_return(series, base_date, h, last_date)
        impact[str(h)] = round(r * 100, 4) if r is not None else None
    return impact


def is_impact_complete(impact) -> bool:
    """True when every horizon in a forward_impact dict is resolved (non-null)."""
    return bool(impact) and all(v is not None for v in impact.values())
