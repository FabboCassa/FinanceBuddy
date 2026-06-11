"""Unit tests for the sentiment-strategy backtester (Phase 3).

Pure math, no DB → SimpleTestCase. Uses synthetic daily prices + news whose
sentiment is engineered to force known entries/exits, so equity, trades, and
metrics are deterministic.
"""
import datetime

from django.test import SimpleTestCase

from core import backtest, constants


UTC = datetime.timezone.utc
START = datetime.datetime(2024, 1, 1, tzinfo=UTC)


def _daily_prices(closes, start=START):
    return [(start + datetime.timedelta(days=i), c) for i, c in enumerate(closes)]


def _news(day_idx, score, start=START):
    return {'timestamp': start + datetime.timedelta(days=day_idx), 'sentiment_score': score}


class BacktestEngineTests(SimpleTestCase):
    def test_insufficient_data_flagged(self):
        prices = _daily_prices([100, 101, 102])  # < BACKTEST_MIN_DAYS
        result = backtest.run_backtest(prices, [])
        self.assertTrue(result['insufficient_data'])
        self.assertIsNone(result['metrics'])
        self.assertEqual(result['equity_curve'], [])

    def test_no_news_means_no_trades(self):
        prices = _daily_prices([100 + i for i in range(10)])
        result = backtest.run_backtest(prices, [])
        self.assertFalse(result['insufficient_data'])
        self.assertEqual(result['trades'], [])
        self.assertEqual(result['signals'], [])
        # Flat equity == initial capital throughout (never invested).
        self.assertEqual(result['metrics']['final_equity'],
                         round(constants.BACKTEST_INITIAL_CAPITAL, 2))
        self.assertEqual(result['metrics']['total_return_pct'], 0.0)

    def test_full_winning_cycle(self):
        # Rising market; buy on a positive sentiment day, sell on a negative one.
        closes = [100, 100, 110, 120, 130, 130, 130, 130]
        prices = _daily_prices(closes)
        news = [_news(1, 0.9), _news(4, -0.9)]  # buy@day1 close=100, sell@day4 close=130
        result = backtest.run_backtest(
            prices, news,
            buy_threshold=0.5, sell_threshold=0.1,
            stop_loss_pct=0, sentiment_window_days=1, initial_capital=1000.0,
            commission_pct=0, slippage_pct=0,  # isolate pure strategy logic
        )
        self.assertEqual(result['metrics']['num_trades'], 1)
        trade = result['trades'][0]
        self.assertEqual(trade['entry_price'], 100.0)
        self.assertEqual(trade['exit_price'], 130.0)
        self.assertEqual(trade['exit_reason'], 'sentiment')
        self.assertAlmostEqual(trade['return_pct'], 30.0, places=2)
        self.assertEqual(result['metrics']['final_equity'], 1300.0)
        self.assertEqual(result['metrics']['win_rate_pct'], 100.0)
        # Two markers (one buy, one sell).
        self.assertEqual([s['type'] for s in result['signals']], ['buy', 'sell'])

    def test_stop_loss_triggers_exit(self):
        # Buy at 100, price collapses → 3% stop-loss must fire before any
        # sentiment exit, capping the loss near -4%.
        closes = [100, 100, 96, 95, 95, 95]
        prices = _daily_prices(closes)
        news = [_news(1, 0.9)]  # buy@day1 close=100; no sell signal afterwards
        result = backtest.run_backtest(
            prices, news,
            buy_threshold=0.5, sell_threshold=-0.9,
            stop_loss_pct=0.03, sentiment_window_days=1, initial_capital=1000.0,
            commission_pct=0, slippage_pct=0,  # isolate pure strategy logic
        )
        trade = result['trades'][0]
        self.assertEqual(trade['exit_reason'], 'stop_loss')
        self.assertEqual(trade['exit_price'], 96.0)  # first close ≤ 97
        self.assertLess(result['metrics']['total_return_pct'], 0)

    def test_open_position_marked_to_market(self):
        # Buy and never exit → position held open, valued at the last close.
        closes = [100, 100, 110, 120, 130]
        prices = _daily_prices(closes)
        news = [_news(1, 0.9)]
        result = backtest.run_backtest(
            prices, news,
            buy_threshold=0.5, sell_threshold=-1.0,
            stop_loss_pct=0, sentiment_window_days=1, initial_capital=1000.0,
            commission_pct=0, slippage_pct=0,  # isolate pure strategy logic
        )
        # The open trade is reported but excluded from closed-trade metrics.
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['trades'][0]['exit_reason'], 'open')
        self.assertEqual(result['metrics']['num_trades'], 0)
        self.assertIsNone(result['metrics']['win_rate_pct'])
        self.assertEqual(result['metrics']['final_equity'], 1300.0)

    def test_buy_hold_and_alpha_reported(self):
        closes = [100, 100, 110, 120, 130, 130]
        prices = _daily_prices(closes)
        news = [_news(1, 0.9), _news(4, -0.9)]
        result = backtest.run_backtest(
            prices, news,
            buy_threshold=0.5, sell_threshold=0.1,
            stop_loss_pct=0, sentiment_window_days=1, initial_capital=1000.0,
        )
        m = result['metrics']
        # Buy & hold over the window: 100 → 130 == +30%.
        self.assertAlmostEqual(m['buy_hold_return_pct'], 30.0, places=2)
        self.assertAlmostEqual(m['alpha_pct'],
                               m['total_return_pct'] - m['buy_hold_return_pct'], places=2)

    def test_equity_curve_spans_all_days(self):
        closes = [100 + i for i in range(10)]
        prices = _daily_prices(closes)
        result = backtest.run_backtest(prices, [])
        self.assertEqual(len(result['equity_curve']), 10)
        self.assertEqual(result['equity_curve'][0]['date'], '2024-01-01')

    def test_flat_equity_reports_no_ratio(self):
        # Buy on the very last day at a non-round price: equity is flat except
        # for float noise from shares*close ≈ cash. Sharpe/Sortino must be N/D,
        # not a spurious value (regression for the 10000/close*close drift).
        closes = [100, 100, 100, 100, 103.7]
        prices = _daily_prices(closes)
        news = [_news(4, 0.9)]  # buy only on the last day
        result = backtest.run_backtest(
            prices, news, buy_threshold=0.5, sell_threshold=-1.0,
            stop_loss_pct=0, sentiment_window_days=1, initial_capital=10000.0,
            commission_pct=0, slippage_pct=0,  # isolate the float-noise regression
        )
        m = result['metrics']
        self.assertEqual(m['num_trades'], 0)            # the lone trade stays open
        self.assertIsNone(m['sharpe_ratio'])
        self.assertIsNone(m['sortino_ratio'])
        self.assertAlmostEqual(m['total_return_pct'], 0.0, places=6)

    def test_execution_costs_reduce_returns(self):
        # The same winning cycle nets less once commission + slippage apply, and
        # the recorded fills move adversely (buy up, sell down) — the honest case
        # that keeps the backtest comparable to the paper trader.
        closes = [100, 100, 110, 120, 130, 130, 130, 130]
        prices = _daily_prices(closes)
        news = [_news(1, 0.9), _news(4, -0.9)]
        common = dict(buy_threshold=0.5, sell_threshold=0.1, stop_loss_pct=0,
                      sentiment_window_days=1, initial_capital=1000.0)

        frictionless = backtest.run_backtest(
            prices, news, commission_pct=0, slippage_pct=0, **common)
        with_costs = backtest.run_backtest(prices, news, **common)  # default costs

        self.assertLess(with_costs['metrics']['total_return_pct'],
                        frictionless['metrics']['total_return_pct'])
        self.assertLess(with_costs['trades'][0]['return_pct'],
                        frictionless['trades'][0]['return_pct'])
        # Slippage worsens the fills: buy above 100, sell below 130.
        self.assertGreater(with_costs['trades'][0]['entry_price'], 100.0)
        self.assertLess(with_costs['trades'][0]['exit_price'], 130.0)
        # Still a winning trade, just less so.
        self.assertGreater(with_costs['metrics']['total_return_pct'], 0)

    def test_max_drawdown_is_non_positive(self):
        closes = [100, 100, 120, 90, 95, 130]
        prices = _daily_prices(closes)
        news = [_news(1, 0.9)]
        result = backtest.run_backtest(
            prices, news, buy_threshold=0.5, sell_threshold=-1.0,
            stop_loss_pct=0, sentiment_window_days=1,
        )
        self.assertLessEqual(result['metrics']['max_drawdown_pct'], 0)


class GridSearchTests(SimpleTestCase):
    def _history(self, n_days=40):
        """Rising series with periodic positive/negative news → real trades."""
        closes = [100 + i for i in range(n_days)]
        news = []
        for d in range(1, n_days - 1, 8):
            news.append(_news(d, 0.9))       # entry signal
            news.append(_news(d + 4, -0.9))  # exit signal
        return _daily_prices(closes), news

    def test_insufficient_history_flagged(self):
        prices = _daily_prices([100, 101, 102])  # train slice < BACKTEST_MIN_DAYS
        result = backtest.grid_search(prices, [])
        self.assertTrue(result['insufficient_data'])
        self.assertEqual(result['results'], [])

    def test_returns_ranked_top_n_with_train_and_test(self):
        prices, news = self._history()
        result = backtest.grid_search(prices, news)
        self.assertFalse(result['insufficient_data'])
        self.assertGreater(result['combos_tested'], 0)
        self.assertLessEqual(len(result['results']), constants.BACKTEST_GRID_TOP_N)
        sharpes = [r['train']['sharpe_ratio'] or 0.0 for r in result['results']
                   if r['train']['sharpe_ratio'] is not None]
        self.assertEqual(sharpes, sorted(sharpes, reverse=True))
        first = result['results'][0]
        self.assertIn('params', first)
        self.assertIn('train', first)
        self.assertIn('test', first)

    def test_nonsense_combos_excluded(self):
        prices, news = self._history()
        result = backtest.grid_search(
            prices, news,
            buy_thresholds=(0.3,), sell_thresholds=(0.3, 0.5), stop_losses=(0.03,),
            windows=(3,),
        )
        # sell >= buy is filtered out entirely → nothing to test
        self.assertEqual(result['combos_tested'], 0)

    def test_split_is_chronological(self):
        prices, news = self._history(n_days=50)
        result = backtest.grid_search(prices, news, train_fraction=0.7)
        self.assertEqual(result['train_days'], 35)
        self.assertEqual(result['test_days'], 15)
        self.assertIsNotNone(result['split_date'])
