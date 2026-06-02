"""DB-backed tests for the Phase 4 relevance task helpers.

The categorization/forward-impact math is covered by test_relevance.py; here we
verify the thin task helpers that persist results idempotently to the DB.
"""
import datetime
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from core import tasks, constants
from core.models import Asset, NewsArticle, PriceData


class CategorizePendingArticlesTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        self.now = timezone.now()

    def _article(self, title, url):
        return NewsArticle.objects.create(
            asset=self.asset, timestamp=self.now, title=title,
            source='Test', url=url,
        )

    def test_categorizes_and_flags_relevance(self):
        self._article('Apple beats Q3 earnings, revenue tops estimates', 'http://x/1')
        self._article('Celebrity gossip and football news roundup', 'http://x/2')

        count = tasks.categorize_pending_articles()
        self.assertEqual(count, 2)

        earnings = NewsArticle.objects.get(url='http://x/1')
        noise = NewsArticle.objects.get(url='http://x/2')
        self.assertEqual(earnings.category, 'earnings')
        self.assertIs(earnings.is_relevant, True)
        self.assertEqual(noise.category, 'noise')
        self.assertIs(noise.is_relevant, False)

    def test_idempotent_skips_already_categorized(self):
        self._article('Fed signals rate hike', 'http://x/1')
        self.assertEqual(tasks.categorize_pending_articles(), 1)
        # Second pass: nothing left to categorize.
        self.assertEqual(tasks.categorize_pending_articles(), 0)


@override_settings(USE_ZERO_SHOT_NLP=True)
class ZeroShotCategorizationTests(TestCase):
    """Zero-shot NLI path with the heavy model mocked out."""

    def setUp(self):
        self.asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        self.now = timezone.now()

    def _article(self, title, url):
        return NewsArticle.objects.create(
            asset=self.asset, timestamp=self.now, title=title, source='Reuters', url=url,
        )

    def _fake_pipeline(self, category, score):
        """A stand-in zero-shot pipeline that always returns `category` as top label."""
        hypothesis = constants.NEWS_CATEGORY_NLI_HYPOTHESES[category]
        def _call(text, candidate_labels=None):
            others = [l for l in (candidate_labels or []) if l != hypothesis]
            return {'labels': [hypothesis] + others,
                    'scores': [score] + [0.0] * len(others)}
        return _call

    def test_uses_nli_verdict(self):
        self._article('Some ambiguous headline', 'http://x/1')
        with mock.patch.object(tasks, 'get_zeroshot_pipeline',
                               return_value=self._fake_pipeline('m_and_a', 0.95)):
            count = tasks.categorize_pending_articles()
        self.assertEqual(count, 1)
        art = NewsArticle.objects.get(url='http://x/1')
        self.assertEqual(art.category, 'm_and_a')
        self.assertIs(art.is_relevant, True)

    def test_falls_back_to_keywords_on_model_error(self):
        self._article('Apple beats Q3 earnings, revenue tops estimates', 'http://x/1')
        with mock.patch.object(tasks, 'get_zeroshot_pipeline', side_effect=RuntimeError('no model')):
            count = tasks.categorize_pending_articles()
        self.assertEqual(count, 1)
        # Keyword fallback still classifies it correctly.
        self.assertEqual(NewsArticle.objects.get(url='http://x/1').category, 'earnings')

    def test_recategorize_all_reprocesses_existing(self):
        art = self._article('headline', 'http://x/1')
        art.category = 'earnings'
        art.is_relevant = True
        art.save(update_fields=['category', 'is_relevant'])

        with mock.patch.object(tasks, 'get_zeroshot_pipeline',
                               return_value=self._fake_pipeline('regulatory', 0.9)):
            tasks.recategorize_all()
        self.assertEqual(NewsArticle.objects.get(url='http://x/1').category, 'regulatory')


class FetchRssNewsTests(TestCase):
    """RSS ingest with feedparser mocked; verifies NER attribution + dedupe."""

    def setUp(self):
        Asset.objects.create(symbol='AAPL', name='Apple Inc.', asset_type='Stock')
        Asset.objects.create(symbol='MSFT', name='Microsoft Corporation', asset_type='Stock')

    def _parsed(self, entries):
        return type('Feed', (), {'entries': entries})()

    def _entry(self, title, link, summary=''):
        import datetime
        return {
            'title': title, 'link': link, 'summary': summary,
            'published_parsed': datetime.datetime(2026, 1, 2, 12, 0).timetuple(),
        }

    @mock.patch.object(constants, 'RSS_FEEDS', ({'source': 'Reuters', 'url': 'http://feed/1'},))
    def test_links_entries_to_assets_by_ner(self):
        entries = [
            self._entry('Apple unveils new iPhone', 'http://news/a'),
            self._entry('Microsoft cloud revenue jumps', 'http://news/b'),
            self._entry('Local bakery wins award', 'http://news/c'),  # matches nothing
        ]
        with mock.patch('core.rss.parse_feed', return_value=self._parsed(entries)):
            inserted = tasks.fetch_rss_news()

        self.assertEqual(inserted, 2)
        self.assertTrue(NewsArticle.objects.filter(asset_id='AAPL', url='http://news/a').exists())
        self.assertTrue(NewsArticle.objects.filter(asset_id='MSFT', url='http://news/b').exists())
        self.assertFalse(NewsArticle.objects.filter(url='http://news/c').exists())
        # Source tier resolved from the registry.
        self.assertEqual(NewsArticle.objects.get(url='http://news/a').source_tier, 'premium')

    @mock.patch.object(constants, 'RSS_FEEDS', ({'source': 'Reuters', 'url': 'http://feed/1'},))
    def test_idempotent_on_rerun(self):
        entries = [self._entry('Apple and Microsoft both gain', 'http://news/x')]
        with mock.patch('core.rss.parse_feed', return_value=self._parsed(entries)):
            first = tasks.fetch_rss_news()
            second = tasks.fetch_rss_news()
        # One article matches two assets → 2 rows first pass, 0 on the second.
        self.assertEqual(first, 2)
        self.assertEqual(second, 0)

    @mock.patch.object(constants, 'RSS_FEEDS', ({'source': 'Reuters', 'url': 'http://feed/1'},))
    def test_feed_error_is_skipped(self):
        with mock.patch('core.rss.parse_feed', side_effect=OSError('network down')):
            self.assertEqual(tasks.fetch_rss_news(), 0)


class BackfillForwardImpactTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        self.start = timezone.make_aware(datetime.datetime(2024, 1, 1))

    def _price(self, day, close):
        ts = self.start + timezone.timedelta(days=day)
        PriceData.objects.create(
            asset=self.asset, timestamp=ts,
            open=close, high=close, low=close, close=close, volume=1000,
        )

    def test_computes_and_matures_impact(self):
        for day, close in enumerate([100, 110, 121, 133.1]):
            self._price(day, close)
        article = NewsArticle.objects.create(
            asset=self.asset, timestamp=self.start, title='news', source='T', url='http://x/1',
        )

        updated = tasks.backfill_forward_impact()
        self.assertEqual(updated, 1)

        article.refresh_from_db()
        self.assertAlmostEqual(article.forward_impact['1'], 10.0, places=1)
        self.assertAlmostEqual(article.forward_impact['3'], 33.1, places=1)
        self.assertIsNone(article.forward_impact['7'])  # not enough history yet

        # Re-run with no new prices: still incomplete, recomputes same value (idempotent result).
        tasks.backfill_forward_impact()
        article.refresh_from_db()
        self.assertIsNone(article.forward_impact['7'])

    def test_skips_when_no_prices(self):
        NewsArticle.objects.create(
            asset=self.asset, timestamp=self.start, title='news', source='T', url='http://x/1',
        )
        self.assertEqual(tasks.backfill_forward_impact(), 0)


class ClassifyPendingSourcesTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(symbol='AAPL', name='Apple', asset_type='Stock')
        self.now = timezone.now()

    def _article(self, source, url):
        return NewsArticle.objects.create(
            asset=self.asset, timestamp=self.now, title='t', source=source, url=url,
        )

    def test_tags_tiers_and_is_idempotent(self):
        self._article('Reuters', 'http://x/1')
        self._article('Il Sole 24 Ore', 'http://x/2')
        self._article('Insider Monkey', 'http://x/3')

        self.assertEqual(tasks.classify_pending_sources(), 3)
        self.assertEqual(NewsArticle.objects.get(url='http://x/1').source_tier, 'premium')
        self.assertEqual(NewsArticle.objects.get(url='http://x/2').source_tier, 'quality')
        self.assertEqual(NewsArticle.objects.get(url='http://x/3').source_tier, 'unverified')
        # Second pass: nothing left untagged.
        self.assertEqual(tasks.classify_pending_sources(), 0)
