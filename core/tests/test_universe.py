"""Tests for the asset universe loader (Phase 4). Pure → SimpleTestCase."""
from django.test import SimpleTestCase

from core import universe


class LoadUniverseTests(SimpleTestCase):
    def setUp(self):
        self.assets = universe.load_universe()
        self.by_symbol = {a['symbol']: a for a in self.assets}

    def test_loads_full_universe(self):
        # Validated global top ~500 (a handful of unlisted tickers removed).
        self.assertGreater(len(self.assets), 480)

    def test_known_names_present(self):
        self.assertEqual(self.by_symbol['AAPL']['name'], 'Apple')
        self.assertEqual(self.by_symbol['NVDA']['name'], 'NVIDIA')
        self.assertIn('MC.PA', self.by_symbol)        # LVMH (Paris)
        self.assertIn('005930.KS', self.by_symbol)    # Samsung (Korea)

    def test_every_entry_well_formed(self):
        for a in self.assets:
            self.assertTrue(a['symbol'])
            self.assertTrue(a['name'])
            self.assertEqual(a['asset_type'], 'Stock')

    def test_no_duplicate_symbols(self):
        symbols = [a['symbol'] for a in self.assets]
        self.assertEqual(len(symbols), len(set(symbols)))

    def test_dropped_unlisted_tickers_absent(self):
        # Tickers with no yfinance data were pruned during validation.
        for gone in ('SBER.ME', 'ROSN.ME', 'IHC.AE', 'ADNOCGAS.AE'):
            self.assertNotIn(gone, self.by_symbol)
