"""DB-backed tests for the paper-trading cycle (Phase 5)."""
import datetime

from django.test import TestCase
from django.utils import timezone

from core import tasks, constants
from core.models import (
    Asset, NewsArticle, PriceData, Portfolio, Position, PaperTrade,
    PortfolioSnapshot,
)


class RunPaperTradingCycleTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.bull = Asset.objects.create(symbol='BULL', name='Bull Co', asset_type='Stock')
        self.bear = Asset.objects.create(symbol='BEAR', name='Bear Co', asset_type='Stock')

    def _news(self, asset, score, days_ago=1, n=3):
        for i in range(n):
            NewsArticle.objects.create(
                asset=asset, timestamp=self.now - datetime.timedelta(days=days_ago, hours=i),
                title=f'{asset.symbol} {i}', source='Reuters',
                url=f'http://x/{asset.symbol}/{days_ago}/{i}',
                sentiment_score=score, sentiment_label='Positivo',
                source_tier='premium', is_relevant=True)

    def _price(self, asset, close, days_ago=0):
        PriceData.objects.create(
            asset=asset, timestamp=self.now - datetime.timedelta(days=days_ago),
            open=close, high=close, low=close, close=close, volume=1000)

    def test_buys_on_strong_sentiment(self):
        self._news(self.bull, 0.8)            # strong → buy
        self._news(self.bear, 0.0)            # weak → no buy
        self._price(self.bull, 100.0)
        self._price(self.bear, 50.0)

        result = tasks.run_paper_trading_cycle()

        self.assertEqual(result['bought'], 1)
        self.assertEqual(result['sold'], 0)
        self.assertTrue(Position.objects.filter(asset_id='BULL').exists())
        self.assertFalse(Position.objects.filter(asset_id='BEAR').exists())
        # A BUY trade was logged and cash dropped by its gross value *plus* the
        # commission (the fill price also carries slippage above the 100.0 close).
        from core import paper_trading
        trade = PaperTrade.objects.get(asset_id='BULL', side='BUY')
        portfolio = Portfolio.objects.get()
        fee = paper_trading.commission(trade.value)
        self.assertAlmostEqual(
            portfolio.cash, constants.PAPER_INITIAL_CAPITAL - trade.value - fee, places=2)
        self.assertGreater(trade.price, 100.0)  # slippage made the buy fill worse

    def test_does_not_double_open_held_asset(self):
        self._news(self.bull, 0.8)
        self._price(self.bull, 100.0)
        tasks.run_paper_trading_cycle()
        tasks.run_paper_trading_cycle()  # still bullish, already held
        self.assertEqual(Position.objects.filter(asset_id='BULL').count(), 1)
        self.assertEqual(PaperTrade.objects.filter(asset_id='BULL', side='BUY').count(), 1)

    def test_stop_loss_closes_position(self):
        portfolio = tasks.get_or_create_default_portfolio()
        Position.objects.create(portfolio=portfolio, asset=self.bull,
                                quantity=10.0, avg_entry_price=100.0)
        portfolio.cash = 0.0
        portfolio.save()
        self._price(self.bull, 80.0)  # 20% below entry, beyond the 3% stop

        result = tasks.run_paper_trading_cycle()

        self.assertEqual(result['sold'], 1)
        self.assertFalse(Position.objects.filter(asset_id='BULL').exists())
        sell = PaperTrade.objects.get(asset_id='BULL', side='SELL')
        self.assertEqual(sell.reason, 'stop_loss')
        # Net P&L = round-trip price move at the slippage-adjusted sell fill, minus
        # both the buy and sell commissions → strictly worse than the gross −200.
        from core import paper_trading
        fill = paper_trading.execution_price(80.0, 'sell')
        expected = ((fill - 100.0) * 10.0
                    - paper_trading.commission(10.0 * fill)
                    - paper_trading.commission(10.0 * 100.0))
        self.assertAlmostEqual(sell.realized_pnl, expected, places=2)
        self.assertLess(sell.realized_pnl, (80.0 - 100.0) * 10.0)

    def test_sells_on_sentiment_reversal(self):
        portfolio = tasks.get_or_create_default_portfolio()
        Position.objects.create(portfolio=portfolio, asset=self.bull,
                                quantity=5.0, avg_entry_price=100.0)
        self._news(self.bull, -0.5)   # reversed below sell threshold
        self._price(self.bull, 101.0)  # price fine → only sentiment triggers

        result = tasks.run_paper_trading_cycle()
        self.assertEqual(result['sold'], 1)
        self.assertEqual(PaperTrade.objects.get(side='SELL').reason, 'sentiment')

    def test_writes_snapshot_each_cycle(self):
        self._price(self.bull, 100.0)
        tasks.run_paper_trading_cycle()
        tasks.run_paper_trading_cycle()
        self.assertEqual(PortfolioSnapshot.objects.count(), 2)

    def test_ignores_unverified_source_sentiment(self):
        # Strong sentiment but from an unverified aggregator → no trade.
        NewsArticle.objects.create(
            asset=self.bull, timestamp=self.now - datetime.timedelta(hours=1),
            title='hype', source='Some Blog', url='http://x/blog',
            sentiment_score=0.9, sentiment_label='Positivo',
            source_tier='unverified', is_relevant=True)
        self._price(self.bull, 100.0)
        result = tasks.run_paper_trading_cycle()
        self.assertEqual(result['bought'], 0)

    def test_performance_block_reports_win_rate_and_alpha(self):
        # Open a position, then close it for a profit on a sentiment reversal so
        # there is one winning closed trade and a benchmark to compare against.
        portfolio = tasks.get_or_create_default_portfolio()
        snap = PortfolioSnapshot.objects.create(
            portfolio=portfolio, cash=10000.0, holdings_value=0.0, total_value=10000.0)
        # Backdate inception so the benchmark window spans real price history
        # (timestamp is auto_now_add, so override it after creation).
        PortfolioSnapshot.objects.filter(pk=snap.pk).update(
            timestamp=self.now - datetime.timedelta(days=5))
        Position.objects.create(portfolio=portfolio, asset=self.bull,
                                quantity=10.0, avg_entry_price=100.0)
        self._price(self.bull, 100.0, days_ago=5)  # benchmark start price
        self._news(self.bull, -0.5)                # reversal → sell
        self._price(self.bull, 120.0)              # up 20% → winning trade

        tasks.run_paper_trading_cycle()

        from core.views import PortfolioView
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/api/portfolio/')
        perf = PortfolioView().get(request).data['performance']

        self.assertEqual(perf['num_closed_trades'], 1)
        self.assertEqual(perf['win_rate_pct'], 100.0)
        self.assertIsNotNone(perf['buy_hold_return_pct'])
        self.assertIsNotNone(perf['alpha_pct'])

    def test_respects_max_positions_cap(self):
        portfolio = tasks.get_or_create_default_portfolio()
        # Pre-fill to the cap with dummy positions, then offer a fresh buy signal.
        for i in range(constants.PAPER_MAX_POSITIONS):
            a = Asset.objects.create(symbol=f'X{i}', name=f'X{i}', asset_type='Stock')
            Position.objects.create(portfolio=portfolio, asset=a, quantity=1.0, avg_entry_price=10.0)
            self._price(a, 10.0)  # neutral price, no news → held steady
        self._news(self.bull, 0.9)
        self._price(self.bull, 100.0)

        result = tasks.run_paper_trading_cycle()
        self.assertEqual(result['bought'], 0)
        self.assertFalse(Position.objects.filter(asset_id='BULL').exists())
