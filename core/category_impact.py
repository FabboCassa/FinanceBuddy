"""Phase 4 analysis: which news *themes* actually move prices?

Crosses two fields that ingest already persists on every article — `category`
(theme) and `forward_impact` (% return at +1/3/7 days from publication, no
look-ahead) — into a per-category impact table:

    per horizon:  mean |return|  ·  mean signed return  ·  "mover" rate
                  (share of articles whose |return| ≥ the noise threshold)

This is the measurement bridge to the rung-3 self-supervised classifier: it
shows, with real market reactions, which themes deserve attention — long before
there is enough history to train on. Pure functions; the DB query lives in the
view. Stats only use *resolved* horizons, so the table matures with history.
"""
from core import constants


def _round(x):
    return round(x, 2)


def category_impact(rows, horizons=constants.FORWARD_IMPACT_HORIZONS_DAYS,
                    move_threshold=constants.CATEGORY_IMPACT_MOVE_THRESHOLD_PCT):
    """Aggregate (category, forward_impact) pairs into per-category stats.

    `rows` — iterable of (category, impact_dict) where impact_dict maps
    str(horizon_days) → % return or None (unresolved). Uncategorized articles
    are grouped under their own bucket so coverage stays visible.

    Returns a list of dicts (one per category present), sorted by mean |return|
    at the middle horizon, descending — "loudest themes first".
    """
    buckets = {}  # category -> {str(h): [returns]}
    for category, impact in rows:
        if not impact:
            continue
        cat = category or constants.NEWS_CATEGORY_UNCATEGORIZED
        per_h = buckets.setdefault(cat, {str(h): [] for h in horizons})
        for h in horizons:
            v = impact.get(str(h))
            if v is not None:
                per_h[str(h)].append(float(v))

    results = []
    for cat, per_h in buckets.items():
        horizons_out = {}
        n_max = 0
        for h in horizons:
            vals = per_h[str(h)]
            n = len(vals)
            n_max = max(n_max, n)
            if n == 0:
                horizons_out[str(h)] = None
                continue
            movers = sum(1 for v in vals if abs(v) >= move_threshold)
            horizons_out[str(h)] = {
                'n': n,
                'mean_abs': _round(sum(abs(v) for v in vals) / n),
                'mean': _round(sum(vals) / n),
                'mover_rate': _round(100.0 * movers / n),
            }
        results.append({
            'category': cat,
            'label': constants.NEWS_CATEGORY_LABELS.get(cat, cat),
            'n_articles': n_max,
            'low_sample': n_max < constants.CATEGORY_IMPACT_MIN_ARTICLES,
            'horizons': horizons_out,
        })

    mid = str(horizons[len(horizons) // 2])
    results.sort(
        key=lambda r: (r['horizons'][mid] or {}).get('mean_abs', -1.0),
        reverse=True,
    )
    return results
