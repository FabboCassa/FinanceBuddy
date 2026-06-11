"""On-demand data-freshness report.

Answers "are we really ingesting data?" without digging through Celery logs.
Prints, against the live DB: how many price bars / news articles exist, when the
newest of each arrived, how stale that is, and how far the forward-impact horizons
(the +1/3/7d signal Phase 4 rung 3 will train on) have matured.

Run it locally (the PyCharm runserver venv talks to the same DB as the containers):

    python manage.py data_status
"""
from django.core.management.base import BaseCommand

from core.monitoring import data_health_summary, _ago


class Command(BaseCommand):
    help = "Report data freshness (prices, news, sentiment, forward-impact maturity)."

    def handle(self, *args, **options):
        # All aggregation lives in core.monitoring (shared with the weekly
        # Telegram health report) — this command is just the styled console view.
        s = data_health_summary()
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("FinanceBuddy - data status"))
        w(f"  Assets in universe: {s['assets']}")

        w(self.style.MIGRATE_HEADING("  Prices"))
        w(f"    Total bars: {s['price_bars']}")
        w(f"    Assets covered: {s['assets_with_prices']}/{s['assets']}")
        w(f"    Newest bar: {s['latest_price']} ({_ago(s['latest_price'])})")

        w(self.style.MIGRATE_HEADING("  News & sentiment"))
        w(f"    Total articles: {s['articles']}")
        w(f"    Newest article: {s['latest_news']} ({_ago(s['latest_news'])})")
        w(f"    Pending sentiment: {s['pending_sentiment']}    "
          f"Pending category: {s['pending_category']}")

        w(self.style.MIGRATE_HEADING("  Forward-impact maturity"))
        w(f"    Articles with impact computed: {s['with_impact']}/{s['articles']}")
        w(f"    Fully resolved (+1/3/7d all present): {s['impact_resolved']}")

        if s['price_bars'] == 0 or s['articles'] == 0:
            w(self.style.ERROR("  [!] No data yet - ingestion has not produced anything."))
        elif s['prices_stale']:
            w(self.style.WARNING(
                "  [!] Prices look stale (>2 days). Is celery_worker running and reaching yfinance?"))
        else:
            w(self.style.SUCCESS("  [OK] Data is flowing - prices and news are recent."))
