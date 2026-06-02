"""Unit tests for entity linking (Phase 4 NER). Pure → SimpleTestCase."""
from django.test import SimpleTestCase

from core import entities


ASSETS = [
    ('AAPL', 'Apple Inc.'),
    ('MSFT', 'Microsoft Corporation'),
    ('SWDA.MI', 'iShares Core MSCI World UCITS ETF'),
]


class BuildAliasMapTests(SimpleTestCase):
    def setUp(self):
        self.alias_map = entities.build_alias_map(ASSETS)

    def test_includes_symbol_and_cleaned_name(self):
        self.assertIn('aapl', self.alias_map['AAPL'])
        self.assertIn('apple', self.alias_map['AAPL'])          # 'Inc.' stripped
        self.assertIn('microsoft', self.alias_map['MSFT'])      # 'Corporation' stripped

    def test_exchange_suffix_base_symbol(self):
        self.assertIn('swda', self.alias_map['SWDA.MI'])

    def test_curated_aliases_present(self):
        self.assertIn('iphone', self.alias_map['AAPL'])

    def test_short_aliases_dropped(self):
        for aliases in self.alias_map.values():
            for a in aliases:
                self.assertGreaterEqual(len(a), 3)


class MatchSymbolsTests(SimpleTestCase):
    def setUp(self):
        self.alias_map = entities.build_alias_map(ASSETS)

    def test_matches_company_name(self):
        got = entities.match_symbols('Apple unveils new iPhone at fall event', self.alias_map)
        self.assertEqual(got, {'AAPL'})

    def test_matches_ticker(self):
        got = entities.match_symbols('Shares of MSFT jumped after earnings', self.alias_map)
        self.assertEqual(got, {'MSFT'})

    def test_matches_multiple_assets(self):
        got = entities.match_symbols('Apple and Microsoft both rallied today', self.alias_map)
        self.assertEqual(got, {'AAPL', 'MSFT'})

    def test_no_false_substring_match(self):
        # 'pineapple' must not match 'apple' (whole-word boundary).
        got = entities.match_symbols('The pineapple harvest was strong', self.alias_map)
        self.assertEqual(got, set())

    def test_empty_text(self):
        self.assertEqual(entities.match_symbols('', self.alias_map), set())
        self.assertEqual(entities.match_symbols(None, self.alias_map), set())
