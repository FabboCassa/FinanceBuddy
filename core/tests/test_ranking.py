"""Unit tests for the composite opportunity ranking (Phase 4). Pure → SimpleTestCase."""
from django.test import SimpleTestCase

from core import ranking, constants


def _inputs(**kw):
    base = dict(symbol='AAA', name='A', sent_recent=None, sent_prior=None,
                n_articles=0, rsi=None, macd_hist=None, price_return=None)
    base.update(kw)
    return base


class ScoreAssetTests(SimpleTestCase):
    def test_neutral_inputs_score_midpoint(self):
        r = ranking.score_asset(_inputs())
        self.assertEqual(r['score'], 50.0)        # all components 0 → midpoint
        self.assertTrue(r['low_news'])

    def test_strong_positive_scores_high(self):
        r = ranking.score_asset(_inputs(
            sent_recent=0.9, sent_prior=0.1, n_articles=10,
            rsi=60, macd_hist=0.5, price_return=0.12))
        self.assertGreater(r['score'], 80)
        self.assertFalse(r['low_news'])

    def test_strong_negative_scores_low(self):
        r = ranking.score_asset(_inputs(
            sent_recent=-0.8, sent_prior=0.2, n_articles=10,
            rsi=80, macd_hist=-0.5, price_return=-0.15))
        self.assertLess(r['score'], 20)

    def test_low_news_neutralizes_sentiment(self):
        # Below the article threshold, sentiment + its momentum don't count.
        r = ranking.score_asset(_inputs(sent_recent=0.9, sent_prior=-0.5, n_articles=1))
        self.assertEqual(r['components']['sentiment'], 0.0)
        self.assertEqual(r['components']['sentiment_momentum'], 0.0)
        self.assertTrue(r['low_news'])

    def test_overbought_rsi_is_penalized(self):
        healthy = ranking.score_asset(_inputs(rsi=60, macd_hist=1))['components']['technical']
        overbought = ranking.score_asset(_inputs(rsi=85, macd_hist=1))['components']['technical']
        self.assertGreater(healthy, overbought)

    def test_momentum_saturates(self):
        big = ranking.score_asset(_inputs(price_return=0.50))['components']['momentum']
        self.assertEqual(big, 1.0)                # clipped at full scale

    def test_components_present(self):
        c = ranking.score_asset(_inputs())['components']
        self.assertEqual(set(c), {'sentiment', 'sentiment_momentum', 'technical', 'momentum'})


class RankAssetsTests(SimpleTestCase):
    def test_sorted_with_ranks(self):
        rows = ranking.rank_assets([
            _inputs(symbol='LOW', sent_recent=-0.5, n_articles=5),
            _inputs(symbol='HIGH', sent_recent=0.8, sent_prior=0.0, n_articles=5,
                    rsi=60, macd_hist=1, price_return=0.08),
            _inputs(symbol='MID'),
        ])
        self.assertEqual([r['symbol'] for r in rows], ['HIGH', 'MID', 'LOW'])
        self.assertEqual([r['rank'] for r in rows], [1, 2, 3])

    def test_weights_sum_to_one(self):
        total = (constants.RANK_WEIGHT_SENTIMENT + constants.RANK_WEIGHT_SENTIMENT_MOMENTUM
                 + constants.RANK_WEIGHT_TECHNICAL + constants.RANK_WEIGHT_MOMENTUM)
        self.assertAlmostEqual(total, 1.0, places=6)
