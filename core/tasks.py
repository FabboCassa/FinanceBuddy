from __future__ import absolute_import, unicode_literals
import logging
import os
import random
import datetime
import tempfile
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from celery.signals import worker_ready
import yfinance as yf

from core.models import (
    Asset, PriceData, NewsArticle,
    Portfolio, Position, PaperTrade, PortfolioSnapshot,
)
from core import constants

logger = logging.getLogger(__name__)

# yfinance keeps a per-exchange timezone cache in a small sqlite file. On a cold
# cache, threaded batch downloads can emit transient "database is locked" errors
# (and the default ~/.cache path sometimes warns "File exists"). Point it at a
# clean, writable, process-local directory to avoid that contention/noise.
try:
    yf.set_tz_cache_location(os.path.join(tempfile.gettempdir(), f"yf_tz_cache_{os.getpid()}"))
except Exception:  # pragma: no cover - older yfinance without the helper
    pass

# Lazy NLP pipeline loaders
_nlp_pipeline = None
_zeroshot_pipeline = None


def get_nlp_pipeline():
    global _nlp_pipeline
    if _nlp_pipeline is None:
        logger.info("Initializing FinBERT pipeline...")
        from transformers import pipeline
        # ProsusAI/finbert is a pre-trained NLP model for finance sentiment
        _nlp_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=-1)
    return _nlp_pipeline


def get_zeroshot_pipeline():
    """Lazy-load the zero-shot NLI classifier (Phase 4 rung 2). CPU-only."""
    global _zeroshot_pipeline
    if _zeroshot_pipeline is None:
        logger.info("Initializing zero-shot NLI pipeline...")
        from transformers import pipeline
        _zeroshot_pipeline = pipeline(
            "zero-shot-classification", model=constants.ZERO_SHOT_MODEL, device=-1,
        )
    return _zeroshot_pipeline


def _categorize_with_nli(article):
    """Return a theme category for an article via zero-shot NLI, or raise on failure."""
    from core import relevance
    pipe = get_zeroshot_pipeline()
    text = f"{article.title}. {article.extracted_text}".strip()[:1000]
    candidate_labels = list(constants.NEWS_CATEGORY_NLI_HYPOTHESES.values())
    result = pipe(text, candidate_labels=candidate_labels)
    return relevance.category_from_nli(result['labels'][0], result['scores'][0])


# ---------------------------------------------------------------------------
# Reusable helpers (shared by Celery beat tasks and the bootstrap command)
# ---------------------------------------------------------------------------

def seed_default_assets():
    """Idempotently create the asset universe (global top ~500). Returns the queryset."""
    from core.universe import load_universe
    for cfg in load_universe():
        Asset.objects.get_or_create(
            symbol=cfg['symbol'],
            defaults={'name': cfg['name'], 'asset_type': cfg['asset_type']},
        )
    return Asset.objects.all()


def _persist_history(asset, hist):
    """Upsert a yfinance history DataFrame into PriceData. Returns (created, updated)."""
    created_count = 0
    updated_count = 0
    for index, row in hist.iterrows():
        dt = index.to_pydatetime()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        else:
            dt = timezone.localtime(dt)

        _, created = PriceData.objects.update_or_create(
            asset=asset,
            timestamp=dt,
            defaults={
                'open': row['Open'],
                'high': row['High'],
                'low': row['Low'],
                'close': row['Close'],
                'volume': int(row['Volume']),
            },
        )
        if created:
            created_count += 1
        else:
            updated_count += 1
    return created_count, updated_count


def fetch_prices_batched(assets, period, interval, batch_size=None):
    """Fetch + persist prices for many assets via batched yfinance downloads.

    One multi-ticker ``yf.download`` per batch instead of a call per asset, so a
    ~500-name universe stays tractable. Returns (created, updated) totals;
    per-batch and per-symbol errors are logged and skipped.
    """
    batch_size = batch_size or constants.PRICE_FETCH_BATCH_SIZE
    assets = list(assets)
    by_symbol = {a.symbol: a for a in assets}
    symbols = list(by_symbol)
    created_total = updated_total = 0
    with_data = empty = 0  # symbols yfinance actually returned bars for vs. none

    for start in range(0, len(symbols), batch_size):
        batch = symbols[start:start + batch_size]
        try:
            data = yf.download(batch, period=period, interval=interval,
                               group_by='ticker', threads=True, progress=False)
        except Exception as e:
            logger.error(f"Batch price download failed ({batch[0]}…+{len(batch)-1}): {e}")
            continue
        for symbol in batch:
            try:
                sub = data[symbol] if len(batch) > 1 else data
                sub = sub.dropna(how='all')
                if sub.empty:
                    empty += 1
                    continue
                with_data += 1
                c, u = _persist_history(by_symbol[symbol], sub)
                created_total += c
                updated_total += u
            except Exception as e:
                logger.error(f"Price persist failed for {symbol}: {e}")

    # Unambiguous: if `with_data` is 0 the source returned nothing (rate-limited
    # / blocked) — not "everything already up to date". Distinguishing the two is
    # exactly what tells you whether ingestion is really working.
    logger.info(
        "Price fetch (period=%s interval=%s): %d/%d symbols returned data "
        "(%d empty); %d bars created, %d updated.",
        period, interval, with_data, len(symbols), empty, created_total, updated_total,
    )
    return created_total, updated_total


def fetch_price_history(asset, period, interval, fallback=True):
    """Fetch and persist price history for a single asset. Returns (created, updated)."""
    ticker = yf.Ticker(asset.symbol)
    hist = ticker.history(period=period, interval=interval)
    if hist.empty and fallback:
        hist = ticker.history(
            period=constants.FALLBACK_PRICE_PERIOD,
            interval=constants.FALLBACK_PRICE_INTERVAL,
        )
    if hist.empty:
        logger.warning(f"No price data returned for {asset.symbol}.")
        return 0, 0
    return _persist_history(asset, hist)


def _parse_news_timestamp(value):
    """Coerce a yfinance publish time (epoch int or ISO-8601 str) to aware datetime."""
    tz = timezone.get_current_timezone()
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, tz=tz)
    if isinstance(value, str):
        # New schema: ISO-8601 like "2026-06-01T12:51:47Z".
        dt = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt if timezone.is_aware(dt) else timezone.make_aware(dt, tz)
    return None


def _normalize_news_item(item):
    """Map one yfinance news item (new nested or legacy flat schema) to fields.

    Returns dict(title, url, source, timestamp, summary) or None if incomplete.
    """
    content = item.get('content') if isinstance(item, dict) else None
    if content:  # New schema (yfinance >= 0.2.40): payload nested under 'content'.
        url_obj = content.get('canonicalUrl') or content.get('clickThroughUrl') or {}
        provider = content.get('provider') or {}
        title = content.get('title')
        url = url_obj.get('url')
        source = provider.get('displayName', 'Yahoo Finance')
        raw_time = content.get('pubDate') or content.get('displayTime')
        summary = content.get('summary', '')
    else:  # Legacy flat schema.
        title = item.get('title')
        url = item.get('link')
        source = item.get('publisher', 'Yahoo Finance')
        raw_time = item.get('providerPublishTime')
        summary = item.get('summary', '')

    pub_date = _parse_news_timestamp(raw_time)
    if not title or not url or pub_date is None:
        return None
    return {'title': title, 'url': url, 'source': source,
            'timestamp': pub_date, 'summary': summary}


def fetch_news_for_asset(asset):
    """Fetch and persist news for a single asset. Returns count of new articles."""
    ticker = yf.Ticker(asset.symbol)
    news_items = ticker.news
    if not news_items:
        logger.info(f"No news found for {asset.symbol}.")
        return 0

    inserted_count = 0
    for item in news_items:
        fields = _normalize_news_item(item)
        if fields is None:
            continue

        from core import sources
        _, created = NewsArticle.objects.get_or_create(
            asset=asset,
            url=fields['url'],
            defaults={
                'title': fields['title'],
                'source': fields['source'],
                'timestamp': fields['timestamp'],
                'extracted_text': fields['summary'],
                'source_tier': sources.source_tier(fields['source']),
            },
        )
        if created:
            inserted_count += 1
    return inserted_count


def fetch_rss_news():
    """Ingest curated RSS feeds and attribute each item to tracked assets (NER).

    General-interest feeds carry no ticker, so every entry is linked to assets
    via the alias-based entity linker; an item matching several assets is stored
    once per asset (the (asset, url) unique key dedupes re-runs). Source tier is
    resolved from the curated registry. Per-feed errors are logged and skipped.
    Returns the count of newly inserted articles.
    """
    from core import rss, entities, sources

    assets = list(Asset.objects.values_list('symbol', 'name'))
    if not assets:
        return 0
    alias_map = entities.build_alias_map(assets)

    inserted = 0
    for feed in constants.RSS_FEEDS:
        try:
            parsed = rss.parse_feed(feed['url'])
        except Exception as e:
            logger.error(f"RSS fetch failed for {feed['source']} ({feed['url']}): {e}")
            continue

        for entry in parsed.entries[:constants.RSS_MAX_ENTRIES_PER_FEED]:
            fields = rss.normalize_entry(entry, feed['source'])
            if fields is None:
                continue

            symbols = entities.match_symbols(
                f"{fields['title']} {fields['summary']}", alias_map)
            for symbol in symbols:
                _, created = NewsArticle.objects.get_or_create(
                    asset_id=symbol,
                    url=fields['url'],
                    defaults={
                        'title': fields['title'],
                        'source': fields['source'],
                        'timestamp': fields['timestamp'],
                        'extracted_text': fields['summary'],
                        'source_tier': sources.source_tier(fields['source']),
                    },
                )
                if created:
                    inserted += 1
    if inserted:
        logger.info(f"RSS ingest: inserted {inserted} new articles linked to tracked assets.")
    return inserted


def _score_with_finbert(article):
    """Return (label, score) for an article using FinBERT, or raise on failure."""
    nlp = get_nlp_pipeline()
    result = nlp(article.title[:255])[0]
    label = constants.SENTIMENT_LABEL_MAP.get(result['label'].lower(), 'Neutrale')
    score = result['score']  # Confidence between 0.0 and 1.0
    if label == 'Negativo':
        score = -score
    elif label == 'Neutrale':
        score = (score - 0.5) * 0.2  # Compress toward 0
    return label, score


def _score_with_keywords(article):
    """Return (label, score) using the simulated keyword lexicon fallback."""
    title_lower = article.title.lower()
    pos_hits = sum(1 for kw in constants.POSITIVE_KEYWORDS if kw in title_lower)
    neg_hits = sum(1 for kw in constants.NEGATIVE_KEYWORDS if kw in title_lower)

    if pos_hits > neg_hits:
        return 'Positivo', random.uniform(0.3, 0.95)
    if neg_hits > pos_hits:
        return 'Negativo', random.uniform(-0.95, -0.3)
    return 'Neutrale', random.uniform(-0.15, 0.15)


def score_pending_articles(use_real=None):
    """Assign sentiment to all unscored articles. Returns number scored."""
    if use_real is None:
        use_real = settings.USE_REAL_NLP

    pending_articles = NewsArticle.objects.filter(sentiment_score__isnull=True)
    if not pending_articles.exists():
        logger.info("No pending news articles to analyze.")
        return 0

    logger.info(f"Analyzing sentiment for {pending_articles.count()} articles...")
    scored = 0
    for article in pending_articles:
        label, score = None, None
        if use_real:
            try:
                label, score = _score_with_finbert(article)
            except Exception as e:
                logger.error(f"FinBERT sentiment analysis error: {str(e)}")
                use_real = False  # Fall back permanently for this run

        if label is None:
            label, score = _score_with_keywords(article)

        article.sentiment_label = label
        article.sentiment_score = score
        article.save()
        scored += 1

    logger.info("Sentiment analysis complete.")
    return scored


def categorize_pending_articles(use_nli=None):
    """Assign a theme category + relevance flag to articles missing one.

    Uses zero-shot NLI when enabled (Phase 4 rung 2), falling back per-article to
    the keyword cold-start classifier on any model failure — same graceful-
    degradation contract as FinBERT sentiment. Idempotent: only touches articles
    whose `category` is still null (forward impact matures separately, below).
    """
    from core import relevance

    if use_nli is None:
        use_nli = settings.USE_ZERO_SHOT_NLP

    pending = NewsArticle.objects.filter(category__isnull=True)
    count = 0
    for article in pending:
        category = None
        if use_nli:
            try:
                category = _categorize_with_nli(article)
            except Exception as e:
                logger.error(f"Zero-shot categorization error: {e}")
                use_nli = False  # Fall back permanently for this run.

        if category is None:
            category = relevance.categorize(article.title, article.extracted_text)

        article.category = category
        article.is_relevant = relevance.is_relevant(category)
        article.save(update_fields=['category', 'is_relevant'])
        count += 1
    if count:
        method = 'zero-shot NLI' if use_nli else 'keyword cold-start'
        logger.info(f"Categorized {count} articles ({method}).")
    return count


def recategorize_all(use_nli=None):
    """Clear and recompute category/relevance for ALL articles.

    Use this one-off after enabling zero-shot NLI (or changing the taxonomy) to
    upgrade rows already tagged by the keyword cold-start.
    """
    NewsArticle.objects.update(category=None, is_relevant=None)
    return categorize_pending_articles(use_nli=use_nli)


def classify_pending_sources():
    """Assign a source quality tier to articles missing one. Idempotent.

    New articles get their tier at ingest; this backfills pre-existing rows and
    re-runs cheaply if the curated registry changes (only touches null tiers).
    """
    from core import sources

    pending = NewsArticle.objects.filter(source_tier__isnull=True)
    count = 0
    for article in pending:
        article.source_tier = sources.source_tier(article.source)
        article.save(update_fields=['source_tier'])
        count += 1
    if count:
        logger.info(f"Tagged source quality tier for {count} articles.")
    return count


def backfill_forward_impact():
    """(Re)compute forward price impact for articles whose horizons aren't resolved.

    The forward return at +1/3/7d only exists once that much price history has
    accumulated, so this re-runs each pass and fills horizons in as data arrives
    — skipping articles already fully resolved. This is the supervision signal
    the later self-supervised relevance model will train on.
    """
    from core import relevance

    updated = 0
    for asset in Asset.objects.all():
        price_rows = list(
            PriceData.objects.filter(asset=asset)
            .order_by('timestamp')
            .values_list('timestamp', 'close')
        )
        if not price_rows:
            continue
        for article in NewsArticle.objects.filter(asset=asset):
            if relevance.is_impact_complete(article.forward_impact):
                continue
            impact = relevance.compute_forward_impact(article.timestamp, price_rows)
            if impact != article.forward_impact:
                article.forward_impact = impact
                article.save(update_fields=['forward_impact'])
                updated += 1
    if updated:
        logger.info(f"Updated forward price impact for {updated} articles.")
    return updated


def _last_valid(series):
    """Last non-NaN float in a pandas series, or None."""
    import pandas as pd
    s = series.dropna()
    return float(s.iloc[-1]) if len(s) else None


def gather_ranking_inputs():
    """Assemble per-asset inputs for the composite ranking (sentiment + technical).

    Sentiment is aggregated over two windows (recent vs. prior) from verified,
    non-noise scored news; RSI/MACD/price-return come from each asset's daily
    closes. Returns a list of dicts consumed by ``ranking.rank_assets``.
    """
    from django.db.models import Avg, Count
    from core import correlation, indicators

    now = timezone.now()
    recent_start = now - datetime.timedelta(days=constants.RANK_RECENT_WINDOW_DAYS)
    prior_start = recent_start - datetime.timedelta(days=constants.RANK_PRIOR_WINDOW_DAYS)
    price_since = now - datetime.timedelta(days=4 * constants.RANK_TECH_LOOKBACK_DAYS)

    base = (NewsArticle.objects
            .filter(sentiment_score__isnull=False,
                    source_tier__in=constants.VERIFIED_SOURCE_TIERS)
            .exclude(is_relevant=False))
    recent = {r['asset']: r for r in base.filter(timestamp__gte=recent_start)
              .values('asset').annotate(avg=Avg('sentiment_score'), n=Count('id'))}
    prior = {r['asset']: r for r in base.filter(timestamp__gte=prior_start, timestamp__lt=recent_start)
             .values('asset').annotate(avg=Avg('sentiment_score'))}

    window = constants.RANK_MOMENTUM_WINDOW_DAYS
    inputs = []
    for symbol, name in Asset.objects.values_list('symbol', 'name'):
        r, p = recent.get(symbol), prior.get(symbol)
        rows = (PriceData.objects.filter(asset_id=symbol, timestamp__gte=price_since)
                .order_by('timestamp').values_list('timestamp', 'close'))
        closes = correlation._build_close_by_date(rows)

        rsi_v = macd_v = price_return = None
        if len(closes) >= 2:
            s = closes.astype(float)
            if len(s) > window and s.iloc[-1 - window] != 0:
                price_return = float(s.iloc[-1] / s.iloc[-1 - window] - 1)
            if len(s) >= constants.MACD_SLOW:
                rsi_v = _last_valid(indicators.rsi(s))
                macd_v = _last_valid(indicators.macd(s)['macd_hist'])

        inputs.append({
            'symbol': symbol, 'name': name,
            'sent_recent': r['avg'] if r else None,
            'sent_prior': p['avg'] if p else None,
            'n_articles': r['n'] if r else 0,
            'rsi': rsi_v, 'macd_hist': macd_v, 'price_return': price_return,
        })
    return inputs


# ---------------------------------------------------------------------------
# Phase 5: paper-trading orchestration (thin task + reusable helpers)
# ---------------------------------------------------------------------------

def get_or_create_default_portfolio():
    """Return the singleton virtual portfolio, seeding it with starting cash."""
    portfolio, _ = Portfolio.objects.get_or_create(
        name=constants.PAPER_DEFAULT_PORTFOLIO_NAME,
        defaults={'initial_capital': constants.PAPER_INITIAL_CAPITAL,
                  'cash': constants.PAPER_INITIAL_CAPITAL},
    )
    return portfolio


def _latest_closes(lookback_days=constants.PAPER_PRICE_LOOKBACK_DAYS):
    """{symbol: latest close (float)} from prices within the recent lookback.

    One query, ordered so the last row per asset wins → its most recent close.
    Assets with no recent price are absent (skipped from trading that cycle).
    """
    since = timezone.now() - datetime.timedelta(days=lookback_days)
    closes = {}
    rows = (PriceData.objects.filter(timestamp__gte=since)
            .order_by('asset_id', 'timestamp')
            .values_list('asset_id', 'close'))
    for symbol, close in rows:
        closes[symbol] = float(close)
    return closes


def _window_sentiments(window_days=constants.PAPER_SENTIMENT_WINDOW_DAYS):
    """{symbol: rolling-mean sentiment} over verified, non-noise scored news.

    One query for the trailing window, grouped per asset and reduced with the
    pure ``paper_trading.rolling_sentiment`` so the live signal matches its tests.
    """
    from core import paper_trading
    from collections import defaultdict

    now = timezone.now()
    since = now - datetime.timedelta(days=window_days)
    rows = (NewsArticle.objects
            .filter(sentiment_score__isnull=False,
                    source_tier__in=constants.VERIFIED_SOURCE_TIERS,
                    timestamp__gte=since)
            .exclude(is_relevant=False)
            .values('asset_id', 'timestamp', 'sentiment_score'))

    by_symbol = defaultdict(list)
    for r in rows:
        by_symbol[r['asset_id']].append(r)
    return {symbol: paper_trading.rolling_sentiment(items, window_days, now)
            for symbol, items in by_symbol.items()}


def _execute_sells(portfolio, positions, closes, sentiments):
    """Close positions whose signal says sell. Mutates cash + DB. Returns count."""
    from core import paper_trading
    sold = 0
    for pos in positions:
        price = closes.get(pos.asset_id)
        if price is None:
            continue
        action, reason = paper_trading.latest_signal(
            price, sentiments.get(pos.asset_id), holding=True,
            entry_price=pos.avg_entry_price)
        if action != 'sell':
            continue
        # Sell into an adverse fill, net the commission, and bill the same fee the
        # original buy paid so realized P&L reflects the full round-trip cost.
        fill = paper_trading.execution_price(price, 'sell')
        gross = pos.quantity * fill
        sell_fee = paper_trading.commission(gross)
        buy_fee = paper_trading.commission(pos.quantity * pos.avg_entry_price)
        proceeds = gross - sell_fee
        realized = (fill - pos.avg_entry_price) * pos.quantity - sell_fee - buy_fee
        portfolio.cash += proceeds
        PaperTrade.objects.create(
            portfolio=portfolio, asset_id=pos.asset_id, side='SELL',
            quantity=pos.quantity, price=fill, value=gross,
            reason=reason, realized_pnl=realized)
        pos.delete()
        sold += 1
    return sold


def _execute_buys(portfolio, held_symbols, closes, sentiments, total_equity):
    """Open new positions for buy signals, best sentiment first. Returns count."""
    from core import paper_trading

    candidates = []
    for symbol, sentiment in sentiments.items():
        if symbol in held_symbols:
            continue
        price = closes.get(symbol)
        action, _ = paper_trading.latest_signal(
            price, sentiment, holding=False, entry_price=None)
        if action == 'buy':
            candidates.append((sentiment, symbol, price))
    candidates.sort(reverse=True)  # strongest sentiment gets cash first

    n_open = len(held_symbols)
    bought = 0
    for sentiment, symbol, price in candidates:
        # Size against the adverse fill so cost + commission never overdraws cash.
        fill = paper_trading.execution_price(price, 'buy')
        qty = paper_trading.position_size(total_equity, portfolio.cash, fill, n_open)
        if qty <= 0:
            continue
        gross = qty * fill
        fee = paper_trading.commission(gross)
        portfolio.cash -= gross + fee
        Position.objects.create(
            portfolio=portfolio, asset_id=symbol,
            quantity=qty, avg_entry_price=fill)
        PaperTrade.objects.create(
            portfolio=portfolio, asset_id=symbol, side='BUY',
            quantity=qty, price=fill, value=gross, reason='sentiment')
        n_open += 1
        bought += 1
    return bought


def _mark_to_market(portfolio, closes):
    """Holdings value of all open positions at the latest closes (float)."""
    total = 0.0
    for pos in portfolio.positions.all():
        price = closes.get(pos.asset_id)
        if price is not None:
            total += pos.quantity * price
    return total


def run_paper_trading_cycle(portfolio=None):
    """Apply the sentiment strategy forward once and snapshot the equity.

    Sells first (frees cash + protects via stop-loss), then buys the strongest
    fresh signals with the freed/idle cash, then records a mark-to-market
    snapshot for the equity curve. Idempotent in spirit: only acts on signals,
    never double-opens a held asset.
    """
    portfolio = portfolio or get_or_create_default_portfolio()
    closes = _latest_closes()
    sentiments = _window_sentiments()

    positions = list(portfolio.positions.all())
    sold = _execute_sells(portfolio, positions, closes, sentiments)

    held_symbols = set(portfolio.positions.values_list('asset_id', flat=True))
    total_equity = portfolio.cash + _mark_to_market(portfolio, closes)
    bought = _execute_buys(portfolio, held_symbols, closes, sentiments, total_equity)

    holdings_value = _mark_to_market(portfolio, closes)
    total_value = portfolio.cash + holdings_value
    portfolio.save(update_fields=['cash', 'updated_at'])
    PortfolioSnapshot.objects.create(
        portfolio=portfolio, cash=portfolio.cash,
        holdings_value=holdings_value, total_value=total_value)

    logger.info(
        f"Paper trading: {bought} buys, {sold} sells, "
        f"equity {total_value:.2f} (cash {portfolio.cash:.2f}).")

    # Push the fresh snapshot to any connected dashboards (best-effort).
    from core.realtime import broadcast_portfolio_update
    broadcast_portfolio_update(portfolio)

    return {'bought': bought, 'sold': sold, 'total_value': round(total_value, 2)}


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@shared_task
def fetch_market_data():
    """Periodic task: fetch recent price data for all assets (seeds universe if empty)."""
    assets = Asset.objects.all()
    if not assets.exists():
        logger.info("No assets found. Seeding asset universe.")
        assets = seed_default_assets()

    created, updated = fetch_prices_batched(
        assets,
        period=constants.RECENT_PRICE_PERIOD,
        interval=constants.RECENT_PRICE_INTERVAL,
    )
    # Freshness snapshot: total bars stored + newest timestamp. Watching the
    # latest bar advance day over day confirms history is accumulating (the data
    # the deferred self-supervised relevance model will eventually train on).
    latest = (PriceData.objects.order_by('-timestamp')
              .values_list('timestamp', flat=True).first())
    logger.info(
        "Market data: +%d new / %d updated bars across %d assets; "
        "DB now holds %d bars, latest at %s.",
        created, updated, assets.count(), PriceData.objects.count(), latest,
    )


@shared_task
def fetch_news():
    """Periodic task: fetch news, then trigger sentiment analysis.

    For a large universe, yfinance per-ticker news (no batch API) is polled only
    for a random sample of assets each cycle (`YFINANCE_NEWS_MAX_ASSETS`); the
    rest get coverage from the curated RSS feeds linked via NER. Over many cycles
    the random sample rotates across the whole universe.
    """
    assets = list(Asset.objects.all())
    cap = getattr(settings, 'YFINANCE_NEWS_MAX_ASSETS', constants.YFINANCE_NEWS_MAX_ASSETS_DEFAULT)
    sample = random.sample(assets, min(cap, len(assets))) if cap > 0 else []
    for asset in sample:
        try:
            inserted = fetch_news_for_asset(asset)
            if inserted:
                logger.info(f"Asset {asset.symbol}: newly inserted {inserted} articles.")
        except Exception as e:
            logger.error(f"Error fetching news for {asset.symbol}: {str(e)}")

    if getattr(settings, 'RSS_INGEST_ENABLED', True):
        try:
            fetch_rss_news()
        except Exception as e:
            logger.error(f"RSS ingest run failed: {e}")

    analyze_sentiment.delay()


@shared_task
def analyze_sentiment():
    """Periodic task: score all unscored articles using FinBERT or the keyword fallback."""
    score_pending_articles()


@shared_task
def update_news_relevance():
    """Periodic task (Phase 4): tag source quality, categorize, (re)compute forward impact."""
    tiered = classify_pending_sources()
    categorized = categorize_pending_articles()
    impacted = backfill_forward_impact()
    return {'source_tiered': tiered, 'categorized': categorized, 'forward_impact_updated': impacted}


@shared_task
def compute_rankings():
    """Periodic task (Phase 4): recompute the composite opportunity score per asset."""
    from core import ranking
    from core.models import AssetScore

    ranked = ranking.rank_assets(gather_ranking_inputs())
    for row in ranked:
        AssetScore.objects.update_or_create(
            asset_id=row['symbol'],
            defaults={
                'score': row['score'], 'rank': row['rank'],
                'components': row['components'], 'n_articles': row['n_articles'],
                'low_news': row['low_news'],
            },
        )
    logger.info(f"Computed opportunity rankings for {len(ranked)} assets.")
    return len(ranked)


@shared_task
def run_paper_trading():
    """Periodic task (Phase 5): run one virtual paper-trading cycle."""
    return run_paper_trading_cycle()


@shared_task
def check_sentiment_alerts():
    """Periodic task: fire sentiment-threshold alerts for assets that crossed limits."""
    from core.alerts import run_sentiment_alert_check
    fired = run_sentiment_alert_check()
    return len(fired)


@shared_task
def startup_catch_up():
    """Gap-recovery pipeline run once when the service comes online.

    Designed for intermittent operation (e.g. the stack is opened ~once a day):
    re-pulls the recent price window (covers any offline gap), fetches news,
    scores all pending sentiment synchronously, and evaluates alerts — so a fresh
    boot immediately ingests AND analyzes everything since the last run rather
    than waiting for the next Celery beat tick. All steps are idempotent.
    """
    logger.info("Startup catch-up: recovering data since last run...")
    fetch_market_data()
    assets = list(Asset.objects.all())
    cap = getattr(settings, 'YFINANCE_NEWS_MAX_ASSETS', constants.YFINANCE_NEWS_MAX_ASSETS_DEFAULT)
    for asset in (random.sample(assets, min(cap, len(assets))) if cap > 0 else []):
        try:
            fetch_news_for_asset(asset)
        except Exception as e:
            logger.error(f"Catch-up news fetch failed for {asset.symbol}: {e}")
    if getattr(settings, 'RSS_INGEST_ENABLED', True):
        try:
            fetch_rss_news()
        except Exception as e:
            logger.error(f"Catch-up RSS ingest failed: {e}")
    scored = score_pending_articles()
    classify_pending_sources()
    categorized = categorize_pending_articles()
    backfill_forward_impact()
    compute_rankings()
    run_paper_trading_cycle()
    from core.alerts import run_sentiment_alert_check
    fired = run_sentiment_alert_check()
    logger.info(
        f"Startup catch-up complete: scored {scored} articles, "
        f"categorized {categorized}, fired {len(fired)} alerts."
    )
    return {'scored': scored, 'categorized': categorized, 'alerts': len(fired)}


@worker_ready.connect
def _trigger_startup_catch_up(sender, **kwargs):
    """On every worker boot, dispatch a one-off catch-up so opening the service
    (after hours/days offline) recovers and analyzes the missed window."""
    startup_catch_up.delay()
