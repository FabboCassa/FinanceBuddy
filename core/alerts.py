"""Sentiment-threshold alerting (Phase 2).

Evaluates each asset's rolling average sentiment and fires an alert when it
crosses the configured bullish/bearish thresholds. Alerts are persisted (for
cooldown/dedupe + UI history) and dispatched to every configured channel.

Channels are all optional and env-driven: the log channel is always on, while
Telegram / Discord / Email activate only when their settings are present. Any
channel failure is logged and skipped (graceful degradation) so one broken
channel never blocks the others or the ingest pipeline.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core.models import Asset, NewsArticle, Alert

logger = logging.getLogger(__name__)

_TELEGRAM_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Evaluation (pure functions — easy to unit test)
# ---------------------------------------------------------------------------

def classify_average(avg, low=None, high=None):
    """Return 'Negativo' / 'Positivo' / None for a rolling average sentiment."""
    if avg is None:
        return None
    low = settings.SENTIMENT_ALERT_LOW if low is None else low
    high = settings.SENTIMENT_ALERT_HIGH if high is None else high
    if avg <= low:
        return 'Negativo'
    if avg >= high:
        return 'Positivo'
    return None


def build_message(asset, level, avg, count):
    """Human-readable alert message (also used as the notification body)."""
    if level == 'Negativo':
        headline = f"⚠️ Sentiment ribassista su {asset.symbol}"
    else:
        headline = f"🚀 Sentiment rialzista su {asset.symbol}"
    return (f"{headline} ({asset.name}). "
            f"Media sentiment {avg:+.2f} su {count} notizie nelle ultime "
            f"{settings.ALERT_LOOKBACK_HOURS}h.")


def _recently_alerted(asset, level, now):
    """True if an alert of this asset+level fired within the cooldown window."""
    cutoff = now - timezone.timedelta(hours=settings.ALERT_COOLDOWN_HOURS)
    return Alert.objects.filter(
        asset=asset, level=level, created_at__gte=cutoff,
    ).exists()


# ---------------------------------------------------------------------------
# Dispatch channels
# ---------------------------------------------------------------------------

def _send_telegram(message):
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={'chat_id': chat_id, 'text': message},
                         timeout=_TELEGRAM_TIMEOUT)
    resp.raise_for_status()
    return True


def _send_discord(message):
    webhook = settings.DISCORD_WEBHOOK_URL
    if not webhook:
        return False
    resp = requests.post(webhook, json={'content': message}, timeout=_TELEGRAM_TIMEOUT)
    resp.raise_for_status()
    return True


def _send_email(message):
    recipients = settings.ALERT_EMAIL_RECIPIENTS
    if not recipients:
        return False
    send_mail(
        subject="FinanceBuddy — Sentiment Alert",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=False,
    )
    return True


_CHANNELS = (
    ('telegram', _send_telegram),
    ('discord', _send_discord),
    ('email', _send_email),
)


def dispatch_alert(alert):
    """Send an alert to every configured channel. Returns list of channels hit."""
    logger.info("ALERT %s", alert.message)  # log channel is always on
    delivered = ['log']
    for name, sender in _CHANNELS:
        try:
            if sender(alert.message):
                delivered.append(name)
        except Exception as exc:  # one bad channel must not break the rest
            logger.error("Alert channel '%s' failed: %s", name, exc)
    return delivered


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def evaluate_asset(asset, now):
    """Evaluate one asset; create + dispatch an Alert if a threshold is crossed.

    Returns the created Alert, or None when nothing fires.
    """
    cutoff = now - timezone.timedelta(hours=settings.ALERT_LOOKBACK_HOURS)
    scores = list(
        NewsArticle.objects
        .filter(asset=asset, sentiment_score__isnull=False, timestamp__gte=cutoff)
        .values_list('sentiment_score', flat=True)
    )
    if len(scores) < settings.ALERT_MIN_ARTICLES:
        return None

    avg = sum(scores) / len(scores)
    level = classify_average(avg)
    if level is None or _recently_alerted(asset, level, now):
        return None

    alert = Alert.objects.create(
        asset=asset,
        level=level,
        avg_sentiment=avg,
        article_count=len(scores),
        message=build_message(asset, level, avg, len(scores)),
    )
    dispatch_alert(alert)
    return alert


def run_sentiment_alert_check():
    """Evaluate all assets. Returns the list of newly fired Alert objects."""
    now = timezone.now()
    fired = []
    for asset in Asset.objects.all():
        try:
            alert = evaluate_asset(asset, now)
            if alert:
                fired.append(alert)
        except Exception as exc:
            logger.error("Alert evaluation failed for %s: %s", asset.symbol, exc)
    logger.info("Sentiment alert check complete: %d fired.", len(fired))
    return fired
