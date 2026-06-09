"""Unit tests for the paper-trading decision engine (Phase 5). Pure → SimpleTestCase."""
import datetime

from django.test import SimpleTestCase

from core import paper_trading, constants


def _news(ts, score):
    return {'timestamp': ts, 'sentiment_score': score}


AS_OF = datetime.datetime(2026, 6, 4, 12, 0, tzinfo=datetime.timezone.utc)


class RollingSentimentTests(SimpleTestCase):
    def test_none_when_no_articles_in_window(self):
        self.assertIsNone(paper_trading.rolling_sentiment([], window_days=3, as_of=AS_OF))

    def test_ignores_unscored_articles(self):
        items = [_news(AS_OF, None), _news(AS_OF, 0.8)]
        self.assertAlmostEqual(
            paper_trading.rolling_sentiment(items, 3, AS_OF), 0.8)

    def test_averages_within_window_excludes_older(self):
        recent = _news(AS_OF - datetime.timedelta(days=1), 0.4)
        also_recent = _news(AS_OF - datetime.timedelta(days=2), 0.6)
        too_old = _news(AS_OF - datetime.timedelta(days=10), -0.9)
        avg = paper_trading.rolling_sentiment([recent, also_recent, too_old], 3, AS_OF)
        self.assertAlmostEqual(avg, 0.5)

    def test_excludes_future_articles(self):
        future = _news(AS_OF + datetime.timedelta(days=1), 0.9)
        self.assertIsNone(paper_trading.rolling_sentiment([future], 3, AS_OF))


class LatestSignalTests(SimpleTestCase):
    def test_flat_buys_on_strong_sentiment(self):
        action, reason = paper_trading.latest_signal(
            100.0, 0.7, holding=False, entry_price=None,
            buy_threshold=0.5, sell_threshold=0.1, stop_loss_pct=0.03)
        self.assertEqual((action, reason), ('buy', 'sentiment'))

    def test_flat_holds_when_sentiment_weak(self):
        action, _ = paper_trading.latest_signal(
            100.0, 0.2, holding=False, entry_price=None,
            buy_threshold=0.5, sell_threshold=0.1, stop_loss_pct=0.03)
        self.assertIsNone(action)

    def test_flat_no_signal_without_sentiment(self):
        action, _ = paper_trading.latest_signal(
            100.0, None, holding=False, entry_price=None)
        self.assertIsNone(action)

    def test_holding_sells_on_sentiment_reversal(self):
        action, reason = paper_trading.latest_signal(
            100.0, 0.05, holding=True, entry_price=90.0,
            buy_threshold=0.5, sell_threshold=0.1, stop_loss_pct=0.03)
        self.assertEqual((action, reason), ('sell', 'sentiment'))

    def test_stop_loss_takes_priority(self):
        # Price 8% below entry with a 3% stop → stop fires even if sentiment fine.
        action, reason = paper_trading.latest_signal(
            92.0, 0.9, holding=True, entry_price=100.0,
            buy_threshold=0.5, sell_threshold=0.1, stop_loss_pct=0.03)
        self.assertEqual((action, reason), ('sell', 'stop_loss'))

    def test_stop_loss_protects_with_no_news(self):
        action, reason = paper_trading.latest_signal(
            80.0, None, holding=True, entry_price=100.0, stop_loss_pct=0.03)
        self.assertEqual((action, reason), ('sell', 'stop_loss'))

    def test_holding_steady_returns_no_action(self):
        action, reason = paper_trading.latest_signal(
            99.0, 0.4, holding=True, entry_price=100.0,
            buy_threshold=0.5, sell_threshold=0.1, stop_loss_pct=0.03)
        self.assertEqual((action, reason), (None, None))

    def test_invalid_price_no_signal(self):
        self.assertEqual(
            paper_trading.latest_signal(0.0, 0.9, holding=False, entry_price=None),
            (None, None))


class PositionSizeTests(SimpleTestCase):
    def test_targets_fraction_of_equity(self):
        qty = paper_trading.position_size(
            10000.0, 10000.0, 100.0, 0,
            max_positions=10, fraction=0.10, min_trade_value=50.0)
        self.assertAlmostEqual(qty, 10.0)  # 10% of 10k = 1000 / 100

    def test_capped_by_available_cash(self):
        qty = paper_trading.position_size(
            10000.0, 500.0, 100.0, 0,
            max_positions=10, fraction=0.10, min_trade_value=50.0)
        self.assertAlmostEqual(qty, 5.0)  # only 500 cash → 5 shares

    def test_refused_at_max_positions(self):
        qty = paper_trading.position_size(
            10000.0, 10000.0, 100.0, 10,
            max_positions=10, fraction=0.10, min_trade_value=50.0)
        self.assertEqual(qty, 0.0)

    def test_refuses_dust_orders(self):
        qty = paper_trading.position_size(
            10000.0, 30.0, 100.0, 0,
            max_positions=10, fraction=0.10, min_trade_value=50.0)
        self.assertEqual(qty, 0.0)

    def test_invalid_price_returns_zero(self):
        self.assertEqual(
            paper_trading.position_size(10000.0, 10000.0, 0.0, 0), 0.0)


class ConfigSanityTests(SimpleTestCase):
    def test_position_fraction_within_bounds(self):
        self.assertTrue(0 < constants.PAPER_POSITION_FRACTION <= 1)

    def test_max_positions_positive(self):
        self.assertGreater(constants.PAPER_MAX_POSITIONS, 0)
