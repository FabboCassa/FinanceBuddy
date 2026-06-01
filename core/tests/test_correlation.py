"""Unit tests for the sentiment ↔ forward-return correlation (Phase 2).

Pure math, no DB → SimpleTestCase. Uses a synthetic daily price series and
articles whose sentiment is set equal to the realized forward return, so the
correlation is known exactly (perfect ⇒ r = 1.0).
"""
import datetime

from django.test import SimpleTestCase

from core import constants, correlation


UTC = datetime.timezone.utc


def _daily_prices(closes, start=datetime.datetime(2024, 1, 1, tzinfo=UTC)):
    return [(start + datetime.timedelta(days=i), c) for i, c in enumerate(closes)]


class CorrelationMathTests(SimpleTestCase):
    def setUp(self):
        # Distinct, varied closes so 1-day forward returns differ across dates.
        self.closes = [100 + (i % 5) * 3 + i * 0.5 for i in range(40)]
        self.prices = _daily_prices(self.closes)

    def _return_at(self, base_idx, horizon):
        base = self.closes[base_idx]
        fut = self.closes[base_idx + horizon]
        return (fut - base) / base

    def test_perfect_positive_correlation(self):
        base_indices = [3, 8, 13, 18, 23]
        news = []
        for idx in base_indices:
            news.append({
                'timestamp': self.prices[idx][0],
                'sentiment_score': self._return_at(idx, 1),  # sentiment == realized 1d return
            })
        result = correlation.compute_sentiment_correlation(news, self.prices, horizons=(1,))
        h1 = result['horizons'][0]
        self.assertEqual(h1['n'], 5)
        self.assertAlmostEqual(h1['pearson'], 1.0, places=3)
        self.assertAlmostEqual(h1['spearman'], 1.0, places=3)

    def test_insufficient_samples_returns_none(self):
        news = [
            {'timestamp': self.prices[3][0], 'sentiment_score': 0.5},
            {'timestamp': self.prices[8][0], 'sentiment_score': -0.5},
        ]  # only 2 < CORRELATION_MIN_SAMPLES
        result = correlation.compute_sentiment_correlation(news, self.prices, horizons=(1,))
        self.assertIsNone(result['horizons'][0]['pearson'])
        self.assertEqual(result['sample_size'], 2)

    def test_future_horizon_excluded(self):
        # Article on the last available date → no forward data for any horizon.
        news = [
            {'timestamp': self.prices[-1][0], 'sentiment_score': 0.2},
            {'timestamp': self.prices[-1][0], 'sentiment_score': 0.3},
            {'timestamp': self.prices[-1][0], 'sentiment_score': 0.4},
        ]
        result = correlation.compute_sentiment_correlation(news, self.prices, horizons=(7,))
        self.assertEqual(result['horizons'][0]['n'], 0)
        self.assertIsNone(result['horizons'][0]['pearson'])

    def test_unscored_articles_ignored(self):
        news = [
            {'timestamp': self.prices[3][0], 'sentiment_score': None},
            {'timestamp': self.prices[8][0], 'sentiment_score': 0.1},
        ]
        result = correlation.compute_sentiment_correlation(news, self.prices, horizons=(1,))
        self.assertEqual(result['sample_size'], 1)  # the None one is dropped

    def test_no_prices_returns_empty_matrix(self):
        news = [{'timestamp': self.prices[3][0], 'sentiment_score': 0.5}]
        result = correlation.compute_sentiment_correlation(news, [], horizons=(1, 3, 7))
        self.assertEqual(len(result['horizons']), 3)
        self.assertTrue(all(h['pearson'] is None for h in result['horizons']))
