"""DB-backed test for the ranking task (Phase 4)."""
import datetime

from django.test import TestCase
from django.utils import timezone

from core import tasks
from core.models import Asset, NewsArticle, PriceData, AssetScore


class ComputeRankingsTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.bull = Asset.objects.create(symbol='BULL', name='Bull Co', asset_type='Stock')
        self.bear = Asset.objects.create(symbol='BEAR', name='Bear Co', asset_type='Stock')

    def _news(self, asset, score, days_ago, n=4):
        for i in range(n):
            NewsArticle.objects.create(
                asset=asset, timestamp=self.now - datetime.timedelta(days=days_ago, hours=i),
                title=f'{asset.symbol} {i}', source='Reuters', url=f'http://x/{asset.symbol}/{days_ago}/{i}',
                sentiment_score=score, sentiment_label='Positivo',
                source_tier='premium', is_relevant=True,
            )

    def _prices(self, asset, closes):
        for i, c in enumerate(closes):
            ts = self.now - datetime.timedelta(days=len(closes) - i)
            PriceData.objects.create(asset=asset, timestamp=ts,
                                     open=c, high=c, low=c, close=c, volume=1000)

    def test_ranks_bullish_above_bearish(self):
        # Bull: very positive recent sentiment + rising price; Bear: opposite.
        self._news(self.bull, 0.8, days_ago=2)
        self._news(self.bear, -0.7, days_ago=2)
        self._prices(self.bull, [100 + i for i in range(40)])      # rising
        self._prices(self.bear, [140 - i for i in range(40)])      # falling

        n = tasks.compute_rankings()
        self.assertEqual(n, 2)

        bull = AssetScore.objects.get(asset_id='BULL')
        bear = AssetScore.objects.get(asset_id='BEAR')
        self.assertGreater(bull.score, bear.score)
        self.assertEqual(bull.rank, 1)
        self.assertEqual(bear.rank, 2)
        self.assertIn('sentiment', bull.components)

    def test_idempotent_upsert(self):
        self._news(self.bull, 0.5, days_ago=1)
        self._prices(self.bull, [100 + i for i in range(40)])
        tasks.compute_rankings()
        tasks.compute_rankings()  # second run updates, doesn't duplicate
        self.assertEqual(AssetScore.objects.filter(asset_id='BULL').count(), 1)
