"""Unit tests for the shared equity-curve metrics (pure → SimpleTestCase)."""
from django.test import SimpleTestCase

from core import metrics


class EquityCurveMetricsTests(SimpleTestCase):
    def test_none_with_too_few_points(self):
        self.assertIsNone(metrics.equity_curve_metrics([10000.0]))
        self.assertIsNone(metrics.equity_curve_metrics([]))

    def test_flat_curve_has_no_ratios_but_zero_drawdown(self):
        m = metrics.equity_curve_metrics([10000.0, 10000.0, 10000.0])
        self.assertIsNone(m['sharpe_ratio'])
        self.assertIsNone(m['sortino_ratio'])
        self.assertAlmostEqual(m['max_drawdown_pct'], 0.0)

    def test_rising_curve_positive_sharpe(self):
        m = metrics.equity_curve_metrics([100, 101, 102, 103, 104, 105])
        self.assertIsNotNone(m['sharpe_ratio'])
        self.assertGreater(m['sharpe_ratio'], 0)

    def test_drawdown_is_negative_after_a_dip(self):
        m = metrics.equity_curve_metrics([100, 120, 90, 95, 130])
        # Peak 120 → trough 90 = -25%.
        self.assertAlmostEqual(m['max_drawdown_pct'], -25.0, places=2)


class WinRateTests(SimpleTestCase):
    def test_none_when_no_closed_trades(self):
        self.assertIsNone(metrics.win_rate([None, None]))
        self.assertIsNone(metrics.win_rate([]))

    def test_counts_only_positive_pnl(self):
        self.assertEqual(metrics.win_rate([10.0, -5.0, 3.0, None]), round(2 / 3 * 100, 2))

    def test_break_even_is_not_a_win(self):
        self.assertEqual(metrics.win_rate([0.0, 10.0]), 50.0)


class BuyHoldReturnTests(SimpleTestCase):
    def test_equal_weight_average(self):
        # +10% and +30% → +20% equal-weight.
        self.assertAlmostEqual(
            metrics.buy_hold_return_pct([(100.0, 110.0), (50.0, 65.0)]), 20.0, places=4)

    def test_skips_missing_or_zero_start(self):
        self.assertAlmostEqual(
            metrics.buy_hold_return_pct([(None, 110.0), (0.0, 5.0), (100.0, 120.0)]),
            20.0, places=4)

    def test_none_when_nothing_usable(self):
        self.assertIsNone(metrics.buy_hold_return_pct([(None, 1.0), (0.0, 2.0)]))
