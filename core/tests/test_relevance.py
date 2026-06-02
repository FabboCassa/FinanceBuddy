"""Unit tests for the cold-start news relevance filter (Phase 4).

Pure math/keyword logic, no DB → SimpleTestCase. Forward impact uses synthetic
daily prices so the per-horizon returns are deterministic.
"""
import datetime

from django.test import SimpleTestCase

from core import relevance, constants


UTC = datetime.timezone.utc
START = datetime.datetime(2024, 1, 1, tzinfo=UTC)


def _daily_prices(closes, start=START):
    return [(start + datetime.timedelta(days=i), c) for i, c in enumerate(closes)]


class CategorizeTests(SimpleTestCase):
    def test_earnings_headline(self):
        cat = relevance.categorize('Apple beats Q3 earnings, revenue tops estimates')
        self.assertEqual(cat, 'earnings')

    def test_m_and_a_headline(self):
        cat = relevance.categorize('Microsoft to acquire gaming studio in $10B takeover deal')
        self.assertEqual(cat, 'm_and_a')

    def test_monetary_policy_headline(self):
        cat = relevance.categorize('Fed signals another rate hike as inflation persists')
        self.assertEqual(cat, 'monetary_policy')

    def test_regulatory_headline(self):
        cat = relevance.categorize('Antitrust regulator opens probe into the company')
        self.assertEqual(cat, 'regulatory')

    def test_noise_headline_flagged(self):
        cat = relevance.categorize('CEO spotted at celebrity football match, gossip swirls')
        # noise keywords (celebrity/football/gossip) outvote the lone signal hit.
        self.assertEqual(cat, constants.NEWS_CATEGORY_NOISE)

    def test_unrelated_headline_is_uncategorized(self):
        cat = relevance.categorize('A quiet day in the neighbourhood')
        self.assertEqual(cat, constants.NEWS_CATEGORY_UNCATEGORIZED)

    def test_text_body_contributes(self):
        cat = relevance.categorize('Big news today', 'The merger and acquisition was a takeover bid')
        self.assertEqual(cat, 'm_and_a')


class CategoryFromNliTests(SimpleTestCase):
    def test_confident_label_maps_to_category(self):
        label = constants.NEWS_CATEGORY_NLI_HYPOTHESES['earnings']
        self.assertEqual(relevance.category_from_nli(label, 0.92), 'earnings')

    def test_noise_hypothesis_maps_to_noise(self):
        label = constants.NEWS_CATEGORY_NLI_HYPOTHESES[constants.NEWS_CATEGORY_NOISE]
        self.assertEqual(relevance.category_from_nli(label, 0.8), constants.NEWS_CATEGORY_NOISE)

    def test_low_confidence_is_uncategorized(self):
        label = constants.NEWS_CATEGORY_NLI_HYPOTHESES['m_and_a']
        self.assertEqual(
            relevance.category_from_nli(label, 0.10),
            constants.NEWS_CATEGORY_UNCATEGORIZED,
        )

    def test_unknown_label_is_uncategorized(self):
        self.assertEqual(
            relevance.category_from_nli('something not in the map', 0.99),
            constants.NEWS_CATEGORY_UNCATEGORIZED,
        )


class IsRelevantTests(SimpleTestCase):
    def test_signal_theme_is_relevant(self):
        self.assertIs(relevance.is_relevant('earnings'), True)

    def test_noise_is_not_relevant(self):
        self.assertIs(relevance.is_relevant(constants.NEWS_CATEGORY_NOISE), False)

    def test_uncategorized_is_unknown(self):
        self.assertIsNone(relevance.is_relevant(constants.NEWS_CATEGORY_UNCATEGORIZED))


class ForwardImpactTests(SimpleTestCase):
    def test_returns_none_without_prices(self):
        self.assertIsNone(relevance.compute_forward_impact(START, []))

    def test_known_forward_returns(self):
        # Price doubles each day from 100; +1d from day0 = +100% etc.
        prices = _daily_prices([100, 110, 121, 133.1, 146.41, 161.051, 177.156, 194.872])
        impact = relevance.compute_forward_impact(START, prices, horizons=(1, 3, 7))
        self.assertAlmostEqual(impact['1'], 10.0, places=2)      # 100→110
        self.assertAlmostEqual(impact['3'], 33.1, places=2)      # 100→133.1
        self.assertAlmostEqual(impact['7'], 94.872, places=2)    # 100→194.872

    def test_unresolved_horizon_is_none(self):
        # Only 2 days of history → 3d and 7d horizons cannot resolve yet.
        prices = _daily_prices([100, 105])
        impact = relevance.compute_forward_impact(START, prices, horizons=(1, 3, 7))
        self.assertAlmostEqual(impact['1'], 5.0, places=2)
        self.assertIsNone(impact['3'])
        self.assertIsNone(impact['7'])

    def test_is_impact_complete(self):
        self.assertTrue(relevance.is_impact_complete({'1': 1.0, '3': 2.0, '7': 3.0}))
        self.assertFalse(relevance.is_impact_complete({'1': 1.0, '3': None, '7': 3.0}))
        self.assertFalse(relevance.is_impact_complete(None))
        self.assertFalse(relevance.is_impact_complete({}))
