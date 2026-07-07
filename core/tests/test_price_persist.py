"""DB tests for the bulk price upsert (`tasks._persist_history`).

Exercises the ON CONFLICT path: a re-pull of overlapping timestamps must UPDATE
in place (no duplicate rows, unique_together preserved) while genuinely new bars
are INSERTed, and the returned (created, updated) split must stay accurate — it
is the freshness signal surfaced in the ingest log.
"""
import datetime
from decimal import Decimal

import pandas as pd
from django.test import TestCase
from django.utils import timezone

from core.models import Asset, PriceData
from core.tasks import _persist_history


def _hist(start, closes):
    """A yfinance-shaped OHLCV frame: hourly DatetimeIndex, one row per close."""
    idx = pd.date_range(start=start, periods=len(closes), freq='h', tz='UTC')
    return pd.DataFrame(
        {
            'Open': closes, 'High': [c + 1 for c in closes],
            'Low': [c - 1 for c in closes], 'Close': closes,
            'Volume': [1000 + i for i in range(len(closes))],
        },
        index=idx,
    )


class PersistHistoryTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(symbol='TEST', name='Test Co')
        self.start = datetime.datetime(2026, 1, 1, 9, 0, tzinfo=datetime.timezone.utc)

    def test_first_insert_counts_all_created(self):
        created, updated = _persist_history(self.asset, _hist(self.start, [10, 11, 12]))
        self.assertEqual((created, updated), (3, 0))
        self.assertEqual(PriceData.objects.filter(asset=self.asset).count(), 3)

    def test_overlapping_repull_updates_in_place(self):
        _persist_history(self.asset, _hist(self.start, [10, 11, 12]))
        # Re-pull covers the same 3 bars (new values) + 1 genuinely new bar.
        created, updated = _persist_history(self.asset, _hist(self.start, [99, 98, 20, 21]))
        self.assertEqual((created, updated), (1, 3))
        # No duplicates: still one row per timestamp (4 total, not 7).
        self.assertEqual(PriceData.objects.filter(asset=self.asset).count(), 4)
        # Overlapping bar was overwritten with the new close.
        first = PriceData.objects.get(asset=self.asset, timestamp=self.start)
        self.assertEqual(first.close, Decimal('99.0000'))

    def test_empty_frame_is_noop(self):
        created, updated = _persist_history(self.asset, _hist(self.start, []))
        self.assertEqual((created, updated), (0, 0))
        self.assertEqual(PriceData.objects.filter(asset=self.asset).count(), 0)

    def test_duplicate_timestamps_in_batch_last_wins(self):
        hist = _hist(self.start, [10, 11])
        dup = hist.iloc[[0]].copy()
        dup['Close'] = 77
        hist = pd.concat([hist, dup])  # same first timestamp twice
        created, updated = _persist_history(self.asset, hist)
        self.assertEqual(created, 2)  # two distinct timestamps
        self.assertEqual(
            PriceData.objects.get(asset=self.asset, timestamp=self.start).close,
            Decimal('77.0000'),
        )
