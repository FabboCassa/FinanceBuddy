"""Phase 1 bootstrap command.

Seeds the default asset universe, backfills deep historical prices, fetches
news and (optionally) runs sentiment analysis -- all synchronously, so a fresh
deployment is immediately useful without waiting for the first Celery beat tick.

Idempotent: safe to run on every container start.

Usage:
    python manage.py bootstrap_assets
    python manage.py bootstrap_assets --skip-news --period 5y
    python manage.py bootstrap_assets --no-sentiment
"""
import random

from django.conf import settings
from django.core.management.base import BaseCommand

from core import constants
from core.models import Asset
from core.tasks import (
    seed_default_assets,
    fetch_prices_batched,
    fetch_news_for_asset,
    fetch_rss_news,
    score_pending_articles,
)


class Command(BaseCommand):
    help = "Seed default assets and backfill historical prices, news, and sentiment."

    def add_arguments(self, parser):
        parser.add_argument(
            '--period', default=constants.BOOTSTRAP_PRICE_PERIOD,
            help=f"yfinance history period (default: {constants.BOOTSTRAP_PRICE_PERIOD}).",
        )
        parser.add_argument(
            '--interval', default=constants.BOOTSTRAP_PRICE_INTERVAL,
            help=f"yfinance history interval (default: {constants.BOOTSTRAP_PRICE_INTERVAL}).",
        )
        parser.add_argument(
            '--skip-prices', action='store_true', help="Skip historical price backfill.",
        )
        parser.add_argument(
            '--skip-news', action='store_true', help="Skip news fetching.",
        )
        parser.add_argument(
            '--no-sentiment', action='store_true', help="Skip sentiment scoring.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Bootstrapping FinanceBuddy (Phase 1)..."))

        assets = seed_default_assets()
        self.stdout.write(self.style.SUCCESS(f"  Assets in universe: {assets.count()}"))

        if not options['skip_prices']:
            self._backfill_prices(assets, options['period'], options['interval'])

        if not options['skip_news']:
            self._fetch_news(assets)

        if not options['no_sentiment']:
            scored = score_pending_articles()
            self.stdout.write(self.style.SUCCESS(f"  Sentiment scored: {scored} articles"))

        self.stdout.write(self.style.SUCCESS("Bootstrap complete."))

    def _backfill_prices(self, assets, period, interval):
        from core.models import PriceData
        # Deep-backfill only assets with no price history yet, so re-running the
        # bootstrap on every container boot doesn't re-upsert 2y × ~500 assets.
        # Recent data for already-seeded assets is kept fresh by the periodic
        # batched fetch_market_data instead.
        have_prices = set(PriceData.objects.values_list('asset_id', flat=True).distinct())
        todo = [a for a in assets if a.symbol not in have_prices]
        if not todo:
            self.stdout.write("  Prices already present for all assets; skipping deep backfill.")
            return
        self.stdout.write(f"  Backfilling prices for {len(todo)} new assets ({period} @ {interval})...")
        created, updated = fetch_prices_batched(todo, period=period, interval=interval)
        self.stdout.write(self.style.SUCCESS(f"    +{created} new prices, {updated} updated"))

    def _fetch_news(self, assets):
        """News at bootstrap: curated RSS (broad, via NER) + a capped yfinance sample."""
        self.stdout.write("  Fetching news (RSS feeds + sampled per-ticker)...")
        try:
            rss_inserted = fetch_rss_news()
            self.stdout.write(self.style.SUCCESS(f"    RSS: +{rss_inserted} articles"))
        except Exception as e:
            self.stderr.write(self.style.WARNING(f"    RSS ingest failed: {e}"))

        assets = list(assets)
        cap = getattr(settings, 'YFINANCE_NEWS_MAX_ASSETS', constants.YFINANCE_NEWS_MAX_ASSETS_DEFAULT)
        sample = random.sample(assets, min(cap, len(assets))) if cap > 0 else []
        inserted = 0
        for asset in sample:
            try:
                inserted += fetch_news_for_asset(asset)
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"    {asset.symbol}: news fetch failed: {e}"))
        self.stdout.write(self.style.SUCCESS(f"    yfinance ({len(sample)} assets): +{inserted} articles"))
