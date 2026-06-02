"""Unit tests for the news source quality registry (Phase 4).

Pure registry lookup, no DB → SimpleTestCase.
"""
from django.test import SimpleTestCase

from core import sources, constants


class SourceTierTests(SimpleTestCase):
    def test_premium_wires(self):
        self.assertEqual(sources.source_tier('Reuters'), constants.SOURCE_TIER_PREMIUM)
        self.assertEqual(sources.source_tier('Bloomberg'), constants.SOURCE_TIER_PREMIUM)
        self.assertEqual(sources.source_tier('The Wall Street Journal'), constants.SOURCE_TIER_PREMIUM)

    def test_alias_and_suffix_matching(self):
        # Real Yahoo strings carry suffixes / variants.
        self.assertEqual(sources.source_tier('Reuters Videos'), constants.SOURCE_TIER_PREMIUM)
        self.assertEqual(sources.source_tier('Barrons.com'), constants.SOURCE_TIER_PREMIUM)
        self.assertEqual(sources.source_tier('WSJ'), constants.SOURCE_TIER_PREMIUM)

    def test_quality_national_outlets(self):
        self.assertEqual(sources.source_tier('Il Sole 24 Ore'), constants.SOURCE_TIER_QUALITY)
        self.assertEqual(sources.source_tier('Handelsblatt'), constants.SOURCE_TIER_QUALITY)
        self.assertEqual(sources.source_tier('Nikkei'), constants.SOURCE_TIER_PREMIUM)

    def test_aggregators_are_unverified(self):
        for junk in ('Insider Monkey', 'Stocktwits', 'Simply Wall St.',
                     'GuruFocus.com', 'TipRanks', 'Zacks', 'Motley Fool', '24/7 Wall St.'):
            self.assertEqual(sources.source_tier(junk), constants.SOURCE_TIER_UNVERIFIED, junk)

    def test_unknown_and_empty(self):
        self.assertEqual(sources.source_tier('Some Random Blog'), constants.SOURCE_TIER_UNVERIFIED)
        self.assertEqual(sources.source_tier(''), constants.SOURCE_TIER_UNVERIFIED)
        self.assertEqual(sources.source_tier(None), constants.SOURCE_TIER_UNVERIFIED)


class SourceMetaTests(SimpleTestCase):
    def test_meta_resolves_country_language(self):
        canonical, tier, country, lang = sources.source_meta('Il Sole 24 Ore')
        self.assertEqual(canonical, 'Il Sole 24 Ore')
        self.assertEqual(tier, constants.SOURCE_TIER_QUALITY)
        self.assertEqual(country, 'IT')
        self.assertEqual(lang, 'it')

    def test_meta_unknown(self):
        canonical, tier, country, lang = sources.source_meta('Nobody News')
        self.assertIsNone(canonical)
        self.assertEqual(tier, constants.SOURCE_TIER_UNVERIFIED)
        self.assertIsNone(country)
        self.assertIsNone(lang)


class IsVerifiedTests(SimpleTestCase):
    def test_verified_vs_not(self):
        self.assertTrue(sources.is_verified('Financial Times'))
        self.assertTrue(sources.is_verified('MarketWatch'))
        self.assertFalse(sources.is_verified('Insider Monkey'))
