"""Tests for the Phase 4 per-category forward-impact analysis (pure math)."""
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core import constants
from core.category_impact import category_impact
from core.models import Asset, NewsArticle


def _rows(*pairs):
    """(category, impact) pairs straight through (mirrors the values_list)."""
    return list(pairs)


class CategoryImpactMathTests(SimpleTestCase):
    def test_empty_input(self):
        self.assertEqual(category_impact([]), [])

    def test_null_impacts_skipped(self):
        self.assertEqual(category_impact(_rows(('earnings', None))), [])

    def test_aggregates_per_horizon(self):
        rows = _rows(
            ('earnings', {'1': 2.0, '3': 4.0, '7': None}),
            ('earnings', {'1': -2.0, '3': -1.0, '7': 6.0}),
        )
        [res] = category_impact(rows)
        self.assertEqual(res['category'], 'earnings')
        self.assertEqual(res['n_articles'], 2)
        h1 = res['horizons']['1']
        self.assertEqual(h1['n'], 2)
        self.assertEqual(h1['mean_abs'], 2.0)     # (2+2)/2
        self.assertEqual(h1['mean'], 0.0)         # (2-2)/2
        # 7d horizon has only one resolved value
        self.assertEqual(res['horizons']['7']['n'], 1)

    def test_mover_rate_uses_threshold(self):
        rows = _rows(
            ('ma', {'1': 0.5, '3': 3.0, '7': 0.0}),
            ('ma', {'1': 0.1, '3': 0.5, '7': 0.0}),
        )
        [res] = category_impact(rows, move_threshold=2.0)
        self.assertEqual(res['horizons']['3']['mover_rate'], 50.0)
        self.assertEqual(res['horizons']['1']['mover_rate'], 0.0)

    def test_uncategorized_bucketed_and_low_sample_flagged(self):
        [res] = category_impact(_rows((None, {'1': 1.0, '3': 1.0, '7': 1.0})))
        self.assertEqual(res['category'], constants.NEWS_CATEGORY_UNCATEGORIZED)
        self.assertTrue(res['low_sample'])

    def test_sorted_by_mid_horizon_mean_abs(self):
        rows = _rows(
            ('noise', {'1': 0.1, '3': 0.2, '7': 0.1}),
            ('earnings', {'1': 1.0, '3': 5.0, '7': 2.0}),
        )
        results = category_impact(rows)
        self.assertEqual([r['category'] for r in results], ['earnings', 'noise'])


class CategoryImpactEndpointTests(TestCase):
    def test_endpoint_filters_by_asset(self):
        a1 = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        a2 = Asset.objects.create(symbol='MSFT', name='Microsoft', asset_type='Stock')
        now = timezone.now()
        NewsArticle.objects.create(asset=a1, timestamp=now, title='t1', source='s',
                                   url='http://x/1', category='earnings',
                                   forward_impact={'1': 3.0, '3': 4.0, '7': 5.0})
        NewsArticle.objects.create(asset=a2, timestamp=now, title='t2', source='s',
                                   url='http://x/2', category='ma',
                                   forward_impact={'1': 1.0, '3': 1.0, '7': 1.0})

        data = self.client.get('/api/category-impact/').json()
        self.assertEqual(data['total_articles'], 2)
        self.assertEqual(len(data['categories']), 2)

        data = self.client.get('/api/category-impact/', {'asset': 'AAPL'}).json()
        self.assertEqual(data['total_articles'], 1)
        self.assertEqual(data['categories'][0]['category'], 'earnings')

    def test_endpoint_ignores_articles_without_impact(self):
        a1 = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        NewsArticle.objects.create(asset=a1, timestamp=timezone.now(), title='t',
                                   source='s', url='http://x/1', category='earnings')
        data = self.client.get('/api/category-impact/').json()
        self.assertEqual(data['total_articles'], 0)
        self.assertEqual(data['categories'], [])
