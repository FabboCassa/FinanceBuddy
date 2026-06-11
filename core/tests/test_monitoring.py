"""Tests for operational monitoring (healthz, failure notifications, reports)."""
import datetime
from unittest import mock

from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from core import monitoring, constants
from core.models import Asset, PriceData, NewsArticle


class FailureCooldownTests(SimpleTestCase):
    def setUp(self):
        monitoring._last_failure_notification.clear()

    def test_first_failure_passes_then_cooldown_blocks(self):
        self.assertFalse(monitoring._failure_cooldown_active('core.tasks.fetch_news', now=1000.0))
        self.assertTrue(monitoring._failure_cooldown_active('core.tasks.fetch_news', now=1001.0))

    def test_cooldown_expires(self):
        window = constants.MONITORING_FAILURE_COOLDOWN_MIN * 60
        self.assertFalse(monitoring._failure_cooldown_active('t', now=0.0))
        self.assertFalse(monitoring._failure_cooldown_active('t', now=window + 1.0))

    def test_cooldown_is_per_task(self):
        self.assertFalse(monitoring._failure_cooldown_active('a', now=0.0))
        self.assertFalse(monitoring._failure_cooldown_active('b', now=0.0))

    def test_handle_task_failure_notifies_once(self):
        sender = mock.Mock()
        sender.name = 'core.tasks.fetch_market_data'
        with mock.patch.object(monitoring, 'notify_ops') as notify:
            monitoring.handle_task_failure(sender=sender, exception=ValueError('boom'))
            monitoring.handle_task_failure(sender=sender, exception=ValueError('boom'))
        self.assertEqual(notify.call_count, 1)
        self.assertIn('fetch_market_data', notify.call_args[0][0])


class NotifyOpsTests(SimpleTestCase):
    def test_never_raises_and_reports_false_on_error(self):
        with mock.patch('core.alerts._send_telegram', side_effect=RuntimeError('down')):
            self.assertFalse(monitoring.notify_ops('hello'))

    def test_prefixes_message(self):
        with mock.patch('core.alerts._send_telegram', return_value=True) as send:
            self.assertTrue(monitoring.notify_ops('hello'))
        self.assertIn('hello', send.call_args[0][0])


class HealthzEndpointTests(TestCase):
    def test_ok_when_db_and_redis_up(self):
        with mock.patch('redis.Redis.from_url') as from_url:
            from_url.return_value.ping.return_value = True
            resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'database': 'ok', 'redis': 'ok'})

    def test_503_when_redis_down(self):
        with mock.patch('redis.Redis.from_url', side_effect=ConnectionError('no redis')):
            resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 503)
        self.assertTrue(resp.json()['redis'].startswith('error'))


class HealthReportTests(TestCase):
    def test_report_reflects_db_contents(self):
        asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        now = timezone.now()
        PriceData.objects.create(asset=asset, timestamp=now, open=1, high=1,
                                 low=1, close=1, volume=100)
        NewsArticle.objects.create(asset=asset, timestamp=now, title='t',
                                   source='s', url='http://x/1')
        report = monitoring.build_health_report()
        self.assertIn('Asset tracciati: 1', report)
        self.assertIn('✅', report)  # fresh price → positive verdict

    def test_stale_prices_flagged(self):
        asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        old = timezone.now() - datetime.timedelta(days=10)
        PriceData.objects.create(asset=asset, timestamp=old, open=1, high=1,
                                 low=1, close=1, volume=100)
        summary = monitoring.data_health_summary()
        self.assertTrue(summary['prices_stale'])
        self.assertIn('⚠️', monitoring.build_health_report(summary))
