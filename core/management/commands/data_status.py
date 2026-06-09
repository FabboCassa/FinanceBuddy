"""On-demand data-freshness report.

Answers "are we really ingesting data?" without digging through Celery logs.
Prints, against the live DB: how many price bars / news articles exist, when the
newest of each arrived, how stale that is, and how far the forward-impact horizons
(the +1/3/7d signal Phase 4 rung 3 will train on) have matured.

Run it locally (the PyCharm runserver venv talks to the same DB as the containers):

    python manage.py data_status
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Asset, PriceData, NewsArticle


def _ago(dt):
    """Human 'x ago' for a datetime, or 'never'."""
    if dt is None:
        return "never"
    delta = timezone.now() - dt
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)} min ago"
    if hours < 48:
        return f"{hours:.1f} h ago"
    return f"{delta.days} days ago"


class Command(BaseCommand):
    help = "Report data freshness (prices, news, sentiment, forward-impact maturity)."

    def handle(self, *args, **options):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("FinanceBuddy - data status"))

        assets = Asset.objects.count()
        w(f"  Assets in universe: {assets}")

        # --- Prices ---
        bars = PriceData.objects.count()
        latest_price = (PriceData.objects.order_by('-timestamp')
                        .values_list('timestamp', flat=True).first())
        assets_with_prices = (PriceData.objects.values('asset_id').distinct().count())
        w(self.style.MIGRATE_HEADING("  Prices"))
        w(f"    Total bars: {bars}")
        w(f"    Assets covered: {assets_with_prices}/{assets}")
        w(f"    Newest bar: {latest_price} ({_ago(latest_price)})")

        # --- News + sentiment ---
        articles = NewsArticle.objects.count()
        latest_news = (NewsArticle.objects.order_by('-timestamp')
                       .values_list('timestamp', flat=True).first())
        unscored = NewsArticle.objects.filter(sentiment_score__isnull=True).count()
        uncategorized = NewsArticle.objects.filter(category__isnull=True).count()
        w(self.style.MIGRATE_HEADING("  News & sentiment"))
        w(f"    Total articles: {articles}")
        w(f"    Newest article: {latest_news} ({_ago(latest_news)})")
        w(f"    Pending sentiment: {unscored}    Pending category: {uncategorized}")

        # --- Forward-impact maturity (the supervision signal for Phase 4 rung 3) ---
        from core import relevance
        with_impact = NewsArticle.objects.filter(forward_impact__isnull=False)
        resolved = sum(1 for fi in with_impact.values_list('forward_impact', flat=True)
                       if relevance.is_impact_complete(fi))
        w(self.style.MIGRATE_HEADING("  Forward-impact maturity"))
        w(f"    Articles with impact computed: {with_impact.count()}/{articles}")
        w(f"    Fully resolved (+1/3/7d all present): {resolved}")

        # --- Verdict ---
        stale = latest_price is None or (timezone.now() - latest_price).days >= 2
        if bars == 0 or articles == 0:
            w(self.style.ERROR("  [!] No data yet - ingestion has not produced anything."))
        elif stale:
            w(self.style.WARNING(
                "  [!] Prices look stale (>2 days). Is celery_worker running and reaching yfinance?"))
        else:
            w(self.style.SUCCESS("  [OK] Data is flowing - prices and news are recent."))
