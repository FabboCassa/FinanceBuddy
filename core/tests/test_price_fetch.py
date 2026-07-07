"""Unit tests for the gap-aware recent price-fetch window.

Pure math (``_recent_period_days``), no DB → SimpleTestCase. This is the logic
that stops the every-15-min refresh from blindly re-pulling 30d/1h of the whole
universe (a ~9-minute, ~100k-row fetch that on-demand sessions kill mid-run);
instead it pulls only the gap since the newest stored bar, clamped to
[MIN, MAX] days, so the steady-state tick is seconds while a long offline gap
still recovers up to the cap.
"""
import datetime

from django.test import SimpleTestCase

from core import constants
from core.tasks import _recent_period_days


UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 7, 18, 0, tzinfo=UTC)


class RecentPeriodDaysTests(SimpleTestCase):
    def test_no_history_uses_full_cap(self):
        self.assertEqual(_recent_period_days(None, NOW),
                         constants.RECENT_PRICE_MAX_DAYS)

    def test_up_to_date_uses_min_floor(self):
        # Newest bar is only a few hours old → gap 0 → clamped up to the floor.
        latest = NOW - datetime.timedelta(hours=3)
        self.assertEqual(_recent_period_days(latest, NOW),
                         constants.RECENT_PRICE_MIN_DAYS)

    def test_gap_gets_buffer(self):
        # 7-day offline gap → 7 + buffer, still well under the cap.
        latest = NOW - datetime.timedelta(days=7)
        self.assertEqual(_recent_period_days(latest, NOW),
                         7 + constants.RECENT_PRICE_BUFFER_DAYS)

    def test_long_gap_clamped_to_cap(self):
        latest = NOW - datetime.timedelta(days=400)
        self.assertEqual(_recent_period_days(latest, NOW),
                         constants.RECENT_PRICE_MAX_DAYS)

    def test_never_below_min_or_above_max(self):
        for days in range(0, 60):
            latest = NOW - datetime.timedelta(days=days)
            got = _recent_period_days(latest, NOW)
            self.assertGreaterEqual(got, constants.RECENT_PRICE_MIN_DAYS)
            self.assertLessEqual(got, constants.RECENT_PRICE_MAX_DAYS)
