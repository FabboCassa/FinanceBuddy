from __future__ import absolute_import, unicode_literals
import logging
import random
import datetime
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from celery.signals import worker_ready
import yfinance as yf

from core.models import Asset, PriceData, NewsArticle
from core import constants

logger = logging.getLogger(__name__)

# Lazy NLP pipeline loader
_nlp_pipeline = None


def get_nlp_pipeline():
    global _nlp_pipeline
    if _nlp_pipeline is None:
        logger.info("Initializing FinBERT pipeline...")
        from transformers import pipeline
        # ProsusAI/finbert is a pre-trained NLP model for finance sentiment
        _nlp_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=-1)
    return _nlp_pipeline


# ---------------------------------------------------------------------------
# Reusable helpers (shared by Celery beat tasks and the bootstrap command)
# ---------------------------------------------------------------------------

def seed_default_assets():
    """Idempotently create the default asset universe. Returns the queryset."""
    for cfg in constants.DEFAULT_ASSETS:
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

        _, created = NewsArticle.objects.get_or_create(
            asset=asset,
            url=fields['url'],
            defaults={
                'title': fields['title'],
                'source': fields['source'],
                'timestamp': fields['timestamp'],
                'extracted_text': fields['summary'],
            },
        )
        if created:
            inserted_count += 1
    return inserted_count


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


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@shared_task
def fetch_market_data():
    """Periodic task: fetch recent price data for all assets (seeds defaults if empty)."""
    assets = Asset.objects.all()
    if not assets.exists():
        logger.info("No assets found. Seeding default universe.")
        assets = seed_default_assets()

    for asset in assets:
        logger.info(f"Fetching market data for {asset.symbol}...")
        try:
            created, updated = fetch_price_history(
                asset,
                period=constants.RECENT_PRICE_PERIOD,
                interval=constants.RECENT_PRICE_INTERVAL,
            )
            logger.info(f"Asset {asset.symbol}: created {created} prices, updated {updated} prices.")
        except Exception as e:
            logger.error(f"Error fetching market data for {asset.symbol}: {str(e)}")


@shared_task
def fetch_news():
    """Periodic task: fetch news for all assets, then trigger sentiment analysis."""
    for asset in Asset.objects.all():
        logger.info(f"Fetching news articles for {asset.symbol}...")
        try:
            inserted = fetch_news_for_asset(asset)
            logger.info(f"Asset {asset.symbol}: newly inserted {inserted} articles.")
        except Exception as e:
            logger.error(f"Error fetching news for {asset.symbol}: {str(e)}")

    analyze_sentiment.delay()


@shared_task
def analyze_sentiment():
    """Periodic task: score all unscored articles using FinBERT or the keyword fallback."""
    score_pending_articles()


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
    for asset in Asset.objects.all():
        try:
            fetch_news_for_asset(asset)
        except Exception as e:
            logger.error(f"Catch-up news fetch failed for {asset.symbol}: {e}")
    scored = score_pending_articles()
    from core.alerts import run_sentiment_alert_check
    fired = run_sentiment_alert_check()
    logger.info(f"Startup catch-up complete: scored {scored} articles, fired {len(fired)} alerts.")
    return {'scored': scored, 'alerts': len(fired)}


@worker_ready.connect
def _trigger_startup_catch_up(sender, **kwargs):
    """On every worker boot, dispatch a one-off catch-up so opening the service
    (after hours/days offline) recovers and analyzes the missed window."""
    startup_catch_up.delay()
