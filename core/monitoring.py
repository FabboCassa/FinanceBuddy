"""Operational monitoring for headless (server) deployments.

Three concerns, all reusing the existing Telegram alert channel:

1. **Liveness** — `health_status()` backs the unauthenticated `/healthz`
   endpoint (DB + Redis reachability) for an external uptime monitor.
2. **Task failures** — a Celery `task_failure` signal handler pushes a Telegram
   message when a background task crashes, with a per-task cooldown so a
   repeatedly-failing task can't flood the chat. Registered in CoreConfig.ready().
3. **Data health** — `data_health_summary()` aggregates ingest freshness
   (shared with the `data_status` management command); `build_health_report()`
   renders it as plain text for the weekly Telegram report (beat task
   `send_health_report`).

Everything degrades gracefully: if Telegram is not configured or unreachable,
failures are logged and the app continues (convention #7).
"""
import logging
import time

from django.utils import timezone

from core import constants

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Liveness (backs /healthz)
# ---------------------------------------------------------------------------

def health_status():
    """Check DB and Redis reachability. Returns (dict, all_ok bool)."""
    checks = {}

    try:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception as exc:  # pragma: no cover - exercised via mocks
        checks['database'] = f'error: {exc.__class__.__name__}'

    try:
        import redis as redis_lib
        from django.conf import settings
        redis_lib.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
        checks['redis'] = 'ok'
    except Exception as exc:
        checks['redis'] = f'error: {exc.__class__.__name__}'

    all_ok = all(v == 'ok' for v in checks.values())
    return checks, all_ok


# ---------------------------------------------------------------------------
# 2. Telegram push for operational events (reuses the alert channel)
# ---------------------------------------------------------------------------

def notify_ops(message):
    """Best-effort operational Telegram message; never raises."""
    try:
        from core.alerts import _send_telegram
        return _send_telegram(f"\U0001F527 FinanceBuddy server\n{message}")
    except Exception as exc:
        logger.warning("Ops notification failed: %s", exc)
        return False


# Per-task cooldown so a task failing every cycle doesn't flood Telegram.
_last_failure_notification = {}  # task_name -> monotonic seconds


def _failure_cooldown_active(task_name, now=None):
    now = now if now is not None else time.monotonic()
    last = _last_failure_notification.get(task_name)
    window = constants.MONITORING_FAILURE_COOLDOWN_MIN * 60
    if last is not None and (now - last) < window:
        return True
    _last_failure_notification[task_name] = now
    return False


def handle_task_failure(sender=None, exception=None, **kwargs):
    """Celery `task_failure` receiver: log + Telegram (cooldown-gated)."""
    task_name = getattr(sender, 'name', str(sender))
    logger.error("Task %s failed: %s", task_name, exception)
    if _failure_cooldown_active(task_name):
        return
    notify_ops(
        f"⚠️ Task fallito: {task_name}\n"
        f"{exception.__class__.__name__}: {exception}\n"
        f"(prossima notifica per questo task tra ≥"
        f"{constants.MONITORING_FAILURE_COOLDOWN_MIN} min)"
    )


def register_signal_handlers():
    """Connect Celery signals. Called once from CoreConfig.ready()."""
    from celery.signals import task_failure
    task_failure.connect(handle_task_failure, weak=False)


# ---------------------------------------------------------------------------
# 3. Data-health summary (shared by `data_status` + weekly Telegram report)
# ---------------------------------------------------------------------------

def data_health_summary():
    """Aggregate ingest freshness into a plain dict (no formatting)."""
    from core.models import Asset, PriceData, NewsArticle
    from core import relevance

    latest_price = (PriceData.objects.order_by('-timestamp')
                    .values_list('timestamp', flat=True).first())
    latest_news = (NewsArticle.objects.order_by('-timestamp')
                   .values_list('timestamp', flat=True).first())
    articles = NewsArticle.objects.count()
    with_impact = NewsArticle.objects.filter(forward_impact__isnull=False)
    resolved = sum(1 for fi in with_impact.values_list('forward_impact', flat=True)
                   if relevance.is_impact_complete(fi))

    return {
        'assets': Asset.objects.count(),
        'price_bars': PriceData.objects.count(),
        'assets_with_prices': PriceData.objects.values('asset_id').distinct().count(),
        'latest_price': latest_price,
        'articles': articles,
        'latest_news': latest_news,
        'pending_sentiment': NewsArticle.objects.filter(sentiment_score__isnull=True).count(),
        'pending_category': NewsArticle.objects.filter(category__isnull=True).count(),
        'with_impact': with_impact.count(),
        'impact_resolved': resolved,
        'prices_stale': latest_price is None
                        or (timezone.now() - latest_price).days >= constants.MONITORING_STALE_PRICE_DAYS,
    }


def _ago(dt):
    """Human 'x ago' for a datetime, or 'mai'."""
    if dt is None:
        return 'mai'
    delta = timezone.now() - dt
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)} min fa"
    if hours < 48:
        return f"{hours:.1f} h fa"
    return f"{delta.days} giorni fa"


def build_health_report(summary=None):
    """Render the weekly data-health report as plain text (Telegram-friendly)."""
    s = summary if summary is not None else data_health_summary()
    verdict = ("⚠️ PREZZI STANTII - controllare il worker"
               if s['prices_stale'] else "✅ dati in arrivo regolarmente")
    return (
        "\U0001F4CA Report settimanale dati\n"
        f"Asset tracciati: {s['assets']}\n"
        f"Prezzi: {s['price_bars']} barre su {s['assets_with_prices']} asset "
        f"(ultimo: {_ago(s['latest_price'])})\n"
        f"News: {s['articles']} articoli (ultima: {_ago(s['latest_news'])})\n"
        f"In coda: {s['pending_sentiment']} sentiment, {s['pending_category']} categorie\n"
        f"Forward impact: {s['with_impact']} calcolati, {s['impact_resolved']} risolti +1/3/7g\n"
        f"{verdict}"
    )
