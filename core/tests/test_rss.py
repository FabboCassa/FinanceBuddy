"""Unit tests for RSS entry normalization (Phase 4). Pure → SimpleTestCase."""
import calendar
import datetime

from django.test import SimpleTestCase

from core import rss


def _struct(dt):
    return dt.timetuple()


class NormalizeEntryTests(SimpleTestCase):
    def test_normalizes_full_entry(self):
        dt = datetime.datetime(2026, 1, 2, 12, 0)
        entry = {
            'title': 'Apple rallies on earnings',
            'link': 'http://news/1',
            'summary': 'Strong quarter',
            'published_parsed': _struct(dt),
        }
        out = rss.normalize_entry(entry, 'MarketWatch')
        self.assertEqual(out['title'], 'Apple rallies on earnings')
        self.assertEqual(out['url'], 'http://news/1')
        self.assertEqual(out['source'], 'MarketWatch')
        self.assertEqual(out['summary'], 'Strong quarter')
        self.assertEqual(out['timestamp'].year, 2026)
        self.assertEqual(out['timestamp'].tzinfo, datetime.timezone.utc)

    def test_per_entry_source_overrides_default(self):
        entry = {
            'title': 't', 'link': 'http://news/2',
            'published_parsed': _struct(datetime.datetime(2026, 1, 1)),
            'source': {'title': 'Reuters'},
        }
        self.assertEqual(rss.normalize_entry(entry, 'MarketWatch')['source'], 'Reuters')

    def test_missing_title_or_link_returns_none(self):
        base = {'published_parsed': _struct(datetime.datetime(2026, 1, 1))}
        self.assertIsNone(rss.normalize_entry({**base, 'link': 'http://x'}, 'S'))
        self.assertIsNone(rss.normalize_entry({**base, 'title': 't'}, 'S'))

    def test_missing_timestamp_returns_none(self):
        entry = {'title': 't', 'link': 'http://x'}
        self.assertIsNone(rss.normalize_entry(entry, 'S'))

    def test_timestamp_is_utc_from_epoch(self):
        dt = datetime.datetime(2026, 3, 15, 9, 30)
        entry = {'title': 't', 'link': 'http://x', 'published_parsed': _struct(dt)}
        out = rss.normalize_entry(entry, 'S')
        expected = datetime.datetime.fromtimestamp(calendar.timegm(_struct(dt)), tz=datetime.timezone.utc)
        self.assertEqual(out['timestamp'], expected)
