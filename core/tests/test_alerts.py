"""Tests for sentiment-threshold alerting (Phase 2).

Threshold/classification logic is pure; firing + dedupe + dispatch touch the DB
and settings, so these use TestCase with override_settings and mocked channels.
"""
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from core import alerts
from core.models import Asset, NewsArticle, Alert


class ClassifyTests(TestCase):
    @override_settings(SENTIMENT_ALERT_LOW=-0.6, SENTIMENT_ALERT_HIGH=0.6)
    def test_classify_bands(self):
        self.assertEqual(alerts.classify_average(-0.7), 'Negativo')
        self.assertEqual(alerts.classify_average(0.7), 'Positivo')
        self.assertIsNone(alerts.classify_average(0.0))
        self.assertIsNone(alerts.classify_average(None))

    @override_settings(SENTIMENT_ALERT_LOW=-0.6, SENTIMENT_ALERT_HIGH=0.6)
    def test_boundaries_inclusive(self):
        self.assertEqual(alerts.classify_average(-0.6), 'Negativo')
        self.assertEqual(alerts.classify_average(0.6), 'Positivo')


@override_settings(
    SENTIMENT_ALERT_LOW=-0.6, SENTIMENT_ALERT_HIGH=0.6,
    ALERT_LOOKBACK_HOURS=24, ALERT_COOLDOWN_HOURS=12, ALERT_MIN_ARTICLES=3,
    TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='', DISCORD_WEBHOOK_URL='',
    ALERT_EMAIL_RECIPIENTS=[],
)
class EvaluateAssetTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        self.now = timezone.now()

    def _add_articles(self, scores):
        for i, s in enumerate(scores):
            NewsArticle.objects.create(
                asset=self.asset, timestamp=self.now - timezone.timedelta(hours=1),
                title=f"news {i}", source='Test', url=f"http://x/{i}",
                sentiment_score=s, sentiment_label='Negativo',
            )

    def test_fires_bearish_alert(self):
        self._add_articles([-0.8, -0.7, -0.9])
        alert = alerts.evaluate_asset(self.asset, self.now)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, 'Negativo')
        self.assertEqual(alert.article_count, 3)
        self.assertEqual(Alert.objects.count(), 1)

    def test_no_fire_when_neutral(self):
        self._add_articles([0.1, -0.1, 0.0])
        self.assertIsNone(alerts.evaluate_asset(self.asset, self.now))
        self.assertEqual(Alert.objects.count(), 0)

    def test_min_articles_guard(self):
        self._add_articles([-0.9, -0.9])  # only 2 < ALERT_MIN_ARTICLES
        self.assertIsNone(alerts.evaluate_asset(self.asset, self.now))

    def test_cooldown_dedupe(self):
        self._add_articles([-0.8, -0.7, -0.9])
        first = alerts.evaluate_asset(self.asset, self.now)
        self.assertIsNotNone(first)
        # Second run within cooldown → no new alert.
        second = alerts.evaluate_asset(self.asset, self.now)
        self.assertIsNone(second)
        self.assertEqual(Alert.objects.count(), 1)

    def test_articles_outside_window_ignored(self):
        NewsArticle.objects.create(
            asset=self.asset, timestamp=self.now - timezone.timedelta(hours=48),
            title="old", source='Test', url="http://x/old",
            sentiment_score=-0.9, sentiment_label='Negativo',
        )
        self._add_articles([-0.8, -0.7])  # 2 in-window + 1 old = still < min in-window
        self.assertIsNone(alerts.evaluate_asset(self.asset, self.now))


class DispatchTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(symbol='MSFT', name='Microsoft', asset_type='Stock')
        self.alert = Alert.objects.create(
            asset=self.asset, level='Negativo', avg_sentiment=-0.7,
            article_count=4, message='test message',
        )

    @override_settings(TELEGRAM_BOT_TOKEN='tok', TELEGRAM_CHAT_ID='123',
                       DISCORD_WEBHOOK_URL='', ALERT_EMAIL_RECIPIENTS=[])
    @mock.patch('core.alerts.requests.post')
    def test_telegram_dispatched(self, mock_post):
        mock_post.return_value = mock.Mock(raise_for_status=lambda: None)
        delivered = alerts.dispatch_alert(self.alert)
        self.assertIn('log', delivered)
        self.assertIn('telegram', delivered)
        mock_post.assert_called_once()

    @override_settings(TELEGRAM_BOT_TOKEN='tok', TELEGRAM_CHAT_ID='123',
                       DISCORD_WEBHOOK_URL='', ALERT_EMAIL_RECIPIENTS=[])
    @mock.patch('core.alerts.requests.post', side_effect=Exception('network down'))
    def test_channel_failure_is_isolated(self, _mock_post):
        # A failing channel must not raise; log still counts as delivered.
        delivered = alerts.dispatch_alert(self.alert)
        self.assertEqual(delivered, ['log'])

    @override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='',
                       DISCORD_WEBHOOK_URL='', ALERT_EMAIL_RECIPIENTS=[])
    def test_no_channels_configured_only_log(self):
        self.assertEqual(alerts.dispatch_alert(self.alert), ['log'])
