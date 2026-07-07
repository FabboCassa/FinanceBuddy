"""Tests for the universe refresh (add newly-large / newly-listed companies).

Pure helpers (`parse_marketcap_symbols`, `diff_universe`) -> SimpleTestCase; the
orchestration (`refresh_universe_members`) is a DB test with the network fetch +
yfinance validation mocked, so it stays offline and deterministic.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from core import universe_refresh
from core.models import Asset


# A trimmed slice of the real companiesmarketcap row markup: the ticker lives in
# the logo image path, foreign listings keep their yfinance suffix, and non-logo
# images (favourite star, country flag) must be ignored.
SAMPLE_HTML = """
<tr><td><img src="/img/fav.svg?v2"></td><td>1</td>
  <td><img src="https://companiesmarketcap.com/img/company-logos/64/NVDA.png">
  <a href="/nvidia/marketcap/">NVIDIA <span>NVDA</span></a></td>
  <td><img src="/img/flags/us.svg"></td></tr>
<tr><td><img src="/img/company-logos/64/2222.SR.png">
  <a href="/saudi-aramco/marketcap/">Saudi Aramco</a></td></tr>
<tr><td><img data-src="/img/company-logos/32/BRK-B.D.png"></td></tr>
<tr><td><img src="/img/company-logos/64/005930.KS.webp"></td></tr>
<tr><td><img src="/img/company-logos/64/NVDA.D.png"></td></tr>
"""


class ParseMarketcapSymbolsTests(SimpleTestCase):
    def test_extracts_tickers_in_order(self):
        self.assertEqual(
            universe_refresh.parse_marketcap_symbols(SAMPLE_HTML),
            ['NVDA', '2222.SR', 'BRK-B', '005930.KS'],
        )

    def test_ignores_non_company_images_and_dedups(self):
        syms = universe_refresh.parse_marketcap_symbols(SAMPLE_HTML)
        self.assertNotIn('us', syms)
        self.assertNotIn('fav', syms)
        self.assertEqual(syms.count('NVDA'), 1)

    def test_strips_dark_mode_logo_suffix(self):
        # <TICKER>.D.png is the dark-mode logo; it must collapse to the real
        # ticker, never leak a bogus "NVDA.D" / "BRK-B.D".
        syms = universe_refresh.parse_marketcap_symbols(SAMPLE_HTML)
        self.assertIn('BRK-B', syms)
        self.assertNotIn('BRK-B.D', syms)
        self.assertNotIn('NVDA.D', syms)

    def test_empty_html_is_empty_list(self):
        self.assertEqual(universe_refresh.parse_marketcap_symbols(''), [])
        self.assertEqual(universe_refresh.parse_marketcap_symbols(None), [])


class DiffUniverseTests(SimpleTestCase):
    def test_splits_new_and_dropped(self):
        new, dropped = universe_refresh.diff_universe(
            ranked_symbols=['NVDA', 'AAPL', 'NEWCO'],
            tracked_symbols=['AAPL', 'OLDCO'],
        )
        self.assertEqual(new, ['NVDA', 'NEWCO'])
        self.assertEqual(dropped, ['OLDCO'])

    def test_no_changes(self):
        new, dropped = universe_refresh.diff_universe(['A', 'B'], ['B', 'A'])
        self.assertEqual((new, dropped), ([], []))


class RefreshUniverseMembersTests(TestCase):
    def setUp(self):
        Asset.objects.create(symbol='AAPL', name='Apple')
        Asset.objects.create(symbol='OLDCO', name='Old Co')

    @mock.patch('core.universe_refresh.validate_and_name')
    @mock.patch('core.universe_refresh.fetch_top_marketcap_symbols')
    def test_seeds_new_valid_and_reports_dropped(self, fetch, validate):
        from core.universe_refresh import refresh_universe_members
        fetch.return_value = ['AAPL', 'NEWCO', 'BADTICK']
        validate.side_effect = lambda s: {
            'NEWCO': (True, 'New Co'), 'BADTICK': (False, None)}[s]

        result = refresh_universe_members(top_n=500, backfill=False)

        self.assertEqual(result['added'], 1)
        self.assertEqual(result['added_symbols'], ['NEWCO'])
        self.assertEqual(result['invalid'], 1)
        self.assertTrue(Asset.objects.filter(symbol='NEWCO').exists())
        self.assertFalse(Asset.objects.filter(symbol='BADTICK').exists())
        self.assertIn('OLDCO', result['dropped_symbols'])
        self.assertTrue(Asset.objects.filter(symbol='OLDCO').exists())

    @mock.patch('core.universe_refresh.validate_and_name')
    @mock.patch('core.universe_refresh.fetch_top_marketcap_symbols')
    def test_idempotent_second_run_adds_nothing(self, fetch, validate):
        from core.universe_refresh import refresh_universe_members
        fetch.return_value = ['AAPL', 'NEWCO']
        validate.return_value = (True, 'New Co')

        refresh_universe_members(top_n=500, backfill=False)
        second = refresh_universe_members(top_n=500, backfill=False)
        self.assertEqual(second['added'], 0)

    @mock.patch('core.universe_refresh.fetch_top_marketcap_symbols')
    def test_empty_source_is_safe_noop(self, fetch):
        from core.universe_refresh import refresh_universe_members
        fetch.return_value = []
        result = refresh_universe_members(backfill=False)
        self.assertEqual(result['added'], 0)
        self.assertTrue(Asset.objects.filter(symbol='OLDCO').exists())
