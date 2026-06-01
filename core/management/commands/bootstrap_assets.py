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
from django.core.management.base import BaseCommand

from core import constants
from core.models import Asset
from core.tasks import (
    seed_default_assets,
    fetch_price_history,
    fetch_news_for_asset,
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
        self.stdout.write(f"  Backfilling prices ({period} @ {interval})...")
        for asset in assets:
            try:
                created, updated = fetch_price_history(asset, period=period, interval=interval)
                self.stdout.write(f"    {asset.symbol}: +{created} new, {updated} updated")
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"    {asset.symbol}: price fetch failed: {e}"))

    def _fetch_news(self, assets):
        self.stdout.write("  Fetching news...")
        for asset in assets:
            try:
                inserted = fetch_news_for_asset(asset)
                self.stdout.write(f"    {asset.symbol}: +{inserted} articles")
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"    {asset.symbol}: news fetch failed: {e}"))
