"""Tests for the Phase 4 earnings-calendar enrichment."""
import datetime
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core import tasks
from core.models import Asset


TODAY = datetime.date(2026, 6, 11)


def _ticker_with_dict_calendar(dates):
    t = mock.Mock()
    t.calendar = {'Earnings Date': dates}
    return t


class ExtractEarningsDateTests(SimpleTestCase):
    def test_modern_dict_shape(self):
        t = _ticker_with_dict_calendar([TODAY + datetime.timedelta(days=5)])
        self.assertEqual(tasks._extract_next_earnings_date(t),
                         TODAY + datetime.timedelta(days=5))

    def test_dict_with_timestamps_converted_to_date(self):
        ts = pd.Timestamp('2026-07-01 10:00:00')
        t = _ticker_with_dict_calendar([ts])
        self.assertEqual(tasks._extract_next_earnings_date(t), datetime.date(2026, 7, 1))

    def test_missing_or_empty_calendar(self):
        t = mock.Mock(); t.calendar = {}
        self.assertIsNone(tasks._extract_next_earnings_date(t))
        t = mock.Mock(); t.calendar = {'Earnings Date': []}
        self.assertIsNone(tasks._extract_next_earnings_date(t))
        t = mock.Mock(); t.calendar = None
        self.assertIsNone(tasks._extract_next_earnings_date(t))

    def test_legacy_dataframe_shape(self):
        df = pd.DataFrame({0: [pd.Timestamp('2026-08-15')]},
                          index=['Earnings Date'])
        t = mock.Mock(); t.calendar = df
        self.assertEqual(tasks._extract_next_earnings_date(t), datetime.date(2026, 8, 15))


class RefreshEarningsTaskTests(TestCase):
    def setUp(self):
        self.a1 = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        self.a2 = Asset.objects.create(symbol='MSFT', name='Microsoft', asset_type='Stock')

    def test_refresh_updates_dates_and_checked_at(self):
        target = timezone.localdate() + datetime.timedelta(days=7)
        with mock.patch.object(tasks.yf, 'Ticker',
                               return_value=_ticker_with_dict_calendar([target])):
            updated = tasks.refresh_earnings_for_assets([self.a1])
        self.a1.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(self.a1.next_earnings_date, target)
        self.assertIsNotNone(self.a1.earnings_checked_at)

    def test_per_asset_failure_is_graceful(self):
        with mock.patch.object(tasks.yf, 'Ticker', side_effect=RuntimeError('rate limit')):
            updated = tasks.refresh_earnings_for_assets([self.a1, self.a2])
        self.assertEqual(updated, 0)
        self.a1.refresh_from_db()
        self.assertIsNotNone(self.a1.earnings_checked_at)  # still marked as checked

    def test_rotation_prefers_never_checked(self):
        self.a1.earnings_checked_at = timezone.now()
        self.a1.save()
        with mock.patch.object(tasks.yf, 'Ticker',
                               return_value=_ticker_with_dict_calendar([])), \
             mock.patch.object(tasks.constants, 'EARNINGS_REFRESH_BATCH', 1), \
             mock.patch.object(tasks, 'refresh_earnings_for_assets',
                               wraps=tasks.refresh_earnings_for_assets) as spy:
            tasks.refresh_earnings_calendar()
        [batch] = spy.call_args[0]
        self.assertEqual([a.symbol for a in batch], ['MSFT'])  # never-checked first

    def test_serializer_days_to_earnings(self):
        from core.serializers import AssetSerializer
        self.a1.next_earnings_date = timezone.localdate() + datetime.timedelta(days=3)
        self.a1.save()
        data = AssetSerializer(self.a1).data
        self.assertEqual(data['days_to_earnings'], 3)
        data2 = AssetSerializer(self.a2).data
        self.assertIsNone(data2['days_to_earnings'])
