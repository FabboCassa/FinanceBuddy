"""Unit tests for the pure-pandas technical indicators (Phase 2).

These exercise the math only — no DB access — so they run fast as a plain
TestCase. Known mathematical properties are asserted rather than hand-computed
magic numbers where possible.
"""
import datetime

import pandas as pd
from django.test import SimpleTestCase

from core import constants, indicators


class EmaTests(SimpleTestCase):
    def test_constant_series_ema_is_constant(self):
        s = pd.Series([5.0] * 30)
        result = indicators.ema(s, 10)
        self.assertTrue((result.round(6) == 5.0).all())

    def test_ema_first_value_equals_first_input(self):
        s = pd.Series([10.0, 20.0, 30.0])
        # adjust=False seeds the EMA with the first observation.
        self.assertAlmostEqual(indicators.ema(s, 3).iloc[0], 10.0)


class RsiTests(SimpleTestCase):
    def test_monotonic_increase_rsi_near_100(self):
        s = pd.Series([float(i) for i in range(1, 40)])
        last = indicators.rsi(s, constants.RSI_PERIOD).iloc[-1]
        self.assertGreater(last, 99.0)

    def test_monotonic_decrease_rsi_near_0(self):
        s = pd.Series([float(i) for i in range(40, 1, -1)])
        last = indicators.rsi(s, constants.RSI_PERIOD).iloc[-1]
        self.assertLess(last, 1.0)

    def test_rsi_warmup_is_nan(self):
        s = pd.Series([float(i) for i in range(1, 40)])
        result = indicators.rsi(s, constants.RSI_PERIOD)
        # First (period) points are warm-up and must be NaN.
        self.assertTrue(result.iloc[: constants.RSI_PERIOD].isna().all())

    def test_rsi_bounded(self):
        s = pd.Series([10, 12, 11, 13, 9, 14, 8, 15, 7, 16, 6, 17, 5, 18, 4, 19])
        result = indicators.rsi(s.astype(float), period=5).dropna()
        self.assertTrue(((result >= 0) & (result <= 100)).all())


class MacdTests(SimpleTestCase):
    def test_constant_series_macd_is_zero(self):
        s = pd.Series([42.0] * 60)
        df = indicators.macd(s)
        self.assertAlmostEqual(df['macd'].iloc[-1], 0.0, places=6)
        self.assertAlmostEqual(df['macd_hist'].iloc[-1], 0.0, places=6)

    def test_macd_columns_present(self):
        df = indicators.macd(pd.Series([float(i) for i in range(60)]))
        self.assertEqual(list(df.columns), ['macd', 'macd_signal', 'macd_hist'])


class ComputeIndicatorsTests(SimpleTestCase):
    def _make_inputs(self, n):
        base = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        timestamps = [base + datetime.timedelta(days=i) for i in range(n)]
        closes = [100.0 + i for i in range(n)]
        return timestamps, closes

    def test_returns_all_expected_keys(self):
        ts, closes = self._make_inputs(250)
        result = indicators.compute_indicators(ts, closes)
        for period in constants.EMA_PERIODS:
            self.assertIn(f'ema{period}', result)
        for key in ('rsi', 'macd', 'macd_signal', 'macd_hist'):
            self.assertIn(key, result)

    def test_points_are_epoch_time_value_dicts(self):
        ts, closes = self._make_inputs(60)
        result = indicators.compute_indicators(ts, closes)
        point = result['ema20'][0]
        self.assertIn('time', point)
        self.assertIn('value', point)
        self.assertIsInstance(point['time'], int)
        self.assertEqual(point['time'], int(ts[0].timestamp()))

    def test_rsi_drops_warmup_points(self):
        ts, closes = self._make_inputs(60)
        result = indicators.compute_indicators(ts, closes)
        # RSI has RSI_PERIOD fewer points than EMA (warm-up NaNs removed).
        self.assertEqual(len(result['ema20']), 60)
        self.assertEqual(len(result['rsi']), 60 - constants.RSI_PERIOD)
