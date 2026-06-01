from __future__ import absolute_import, unicode_literals
import logging
import random
import datetime
from django.utils import timezone
from django.conf import settings
from celery import shared_task
import yfinance as yf

from core.models import Asset, PriceData, NewsArticle

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


@shared_task
def fetch_market_data():
    """
    Periodic task to fetch price data using yfinance for all assets in the DB.
    Runs every 15 minutes by default.
    """
    assets = Asset.objects.all()
    if not assets.exists():
        logger.info("No assets found in database. Add assets to trigger price downloads.")
        # Bootstrap default assets for user
        Asset.objects.get_or_create(symbol='AAPL', defaults={'name': 'Apple Inc.', 'asset_type': 'Stock'})
        Asset.objects.get_or_create(symbol='MSFT', defaults={'name': 'Microsoft Corporation', 'asset_type': 'Stock'})
        Asset.objects.get_or_create(symbol='SWDA.MI', defaults={'name': 'iShares Core MSCI World UCITS ETF', 'asset_type': 'ETF'})
        assets = Asset.objects.all()

    for asset in assets:
        logger.info(f"Fetching market data for {asset.symbol}...")
        try:
            ticker = yf.Ticker(asset.symbol)
            # Fetch last 30 days of hourly data for dense charts
            # '1h' interval allows highly detailed markers and interactive charts
            hist = ticker.history(period='30d', interval='1h')
            
            if hist.empty:
                # Fallback to daily data if hourly isn't available
                hist = ticker.history(period='90d', interval='1d')
            
            created_count = 0
            updated_count = 0
            
            for index, row in hist.iterrows():
                # Convert pandas index timestamp to timezone-aware datetime
                dt = index.to_pydatetime()
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                else:
                    dt = timezone.localtime(dt)

                obj, created = PriceData.objects.update_or_create(
                    asset=asset,
                    timestamp=dt,
                    defaults={
                        'open': row['Open'],
                        'high': row['High'],
                        'low': row['Low'],
                        'close': row['Close'],
                        'volume': int(row['Volume'])
                    }
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            
            logger.info(f"Asset {asset.symbol}: created {created_count} prices, updated {updated_count} prices.")
        except Exception as e:
            logger.error(f"Error fetching market data for {asset.symbol}: {str(e)}")


@shared_task
def fetch_news():
    """
    Fetch financial news articles using yfinance's built-in feed for registered assets.
    """
    assets = Asset.objects.all()
    for asset in assets:
        logger.info(f"Fetching news articles for {asset.symbol}...")
        try:
            ticker = yf.Ticker(asset.symbol)
            news_items = ticker.news
            if not news_items:
                logger.info(f"No news found for {asset.symbol}.")
                continue
            
            inserted_count = 0
            for item in news_items:
                # Example: {'uuid': '...', 'title': '...', 'publisher': 'Yahoo Finance', 'link': '...', 'providerPublishTime': 1716...}
                title = item.get('title')
                url = item.get('link')
                source = item.get('publisher', 'Yahoo Finance')
                publish_time_epoch = item.get('providerPublishTime')
                
                if not title or not url or not publish_time_epoch:
                    continue
                
                # Convert epoch timestamp to timezone-aware datetime
                pub_date = datetime.datetime.fromtimestamp(publish_time_epoch, tz=timezone.get_current_timezone())
                
                # We can also capture paragraphs if yfinance gives it, else blank.
                summary = item.get('summary', '')

                # Update or create news article
                # Use URL + Asset as unique identifier to avoid duplicates
                _, created = NewsArticle.objects.get_or_create(
                    asset=asset,
                    url=url,
                    defaults={
                        'title': title,
                        'source': source,
                        'timestamp': pub_date,
                        'extracted_text': summary
                    }
                )
                if created:
                    inserted_count += 1
            
            logger.info(f"Asset {asset.symbol}: newly inserted {inserted_count} articles.")
        except Exception as e:
            logger.error(f"Error fetching news for {asset.symbol}: {str(e)}")
            
    # Trigger sentiment analysis immediately after fetching news
    analyze_sentiment.delay()


@shared_task
def analyze_sentiment():
    """
    Run sentiment analysis for all articles lacking a score/label.
    Uses FinBERT if USE_REAL_NLP=True, otherwise uses simulated sentiment logic.
    """
    pending_articles = NewsArticle.objects.filter(sentiment_score__isnull=True)
    if not pending_articles.exists():
        logger.info("No pending news articles to analyze.")
        return
    
    logger.info(f"Analyzing sentiment for {pending_articles.count()} articles...")
    
    use_real = settings.USE_REAL_NLP
    
    positive_keywords = ['surge', 'gain', 'profit', 'rise', 'up', 'bull', 'growth', 'buy', 'beat', 'higher', 'positive', 'outperform', 'strong']
    negative_keywords = ['drop', 'loss', 'fall', 'down', 'bear', 'sell', 'debt', 'miss', 'lower', 'negative', 'underperform', 'weak', 'plunge', 'warn']

    for article in pending_articles:
        if use_real:
            try:
                nlp = get_nlp_pipeline()
                # Run the model on the title (which holds the densest summary)
                result = nlp(article.title[:255])[0]
                # FinBERT returns labels: 'positive', 'negative', 'neutral'
                label_map = {
                    'positive': 'Positivo',
                    'neutral': 'Neutrale',
                    'negative': 'Negativo'
                }
                label = label_map.get(result['label'].lower(), 'Neutrale')
                score = result['score'] # Confidence score between 0.0 and 1.0
                
                # Map score to the range [-1.0, 1.0] depending on classification
                if label == 'Negativo':
                    score = -score
                elif label == 'Neutrale':
                    score = (score - 0.5) * 0.2  # Closer to 0
                
                article.sentiment_label = label
                article.sentiment_score = score
                article.save()
            except Exception as e:
                logger.error(f"FinBERT sentiment analysis error: {str(e)}")
                use_real = False # Fallback to simulated on failure
        
        # If simulation or fallback
        if not use_real or article.sentiment_score is None:
            # Simulated NLP with high-quality keyword mapping + slight randomness
            title_lower = article.title.lower()
            
            # Count keyword hits
            pos_hits = sum(1 for kw in positive_keywords if kw in title_lower)
            neg_hits = sum(1 for kw in negative_keywords if kw in title_lower)
            
            if pos_hits > neg_hits:
                label = 'Positivo'
                score = random.uniform(0.3, 0.95)
            elif neg_hits > pos_hits:
                label = 'Negativo'
                score = random.uniform(-0.95, -0.3)
            else:
                label = 'Neutrale'
                score = random.uniform(-0.15, 0.15)
                
            article.sentiment_label = label
            article.sentiment_score = score
            article.save()
            
    logger.info("Sentiment analysis complete.")
