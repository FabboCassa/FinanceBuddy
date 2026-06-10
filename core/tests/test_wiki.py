"""Phase 6: smoke tests for the educational Knowledge Base (/wiki/).

The wiki is a static template; these tests pin down the contract the dashboard
relies on: the route resolves, the right template renders, and the anchor ids
targeted by the dashboard's contextual ℹ︎ deep-links keep existing.
"""
from django.test import TestCase
from django.urls import reverse

# Anchor ids referenced by dashboard.html contextual links — keep in sync.
DASHBOARD_DEEP_LINK_ANCHORS = [
    'top-opportunita', 'paper-trading', 'equity-curve', 'sec-metriche',
    'candela-ohlcv', 'ema', 'rsi', 'macd', 'correlazione', 'backtest',
]


class WikiViewTests(TestCase):
    def test_wiki_route_renders(self):
        response = self.client.get(reverse('wiki'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/wiki.html')

    def test_dashboard_deep_link_anchors_exist(self):
        html = self.client.get(reverse('wiki')).content.decode('utf-8')
        for anchor in DASHBOARD_DEEP_LINK_ANCHORS:
            self.assertIn(f'id="{anchor}"', html, f'missing wiki anchor #{anchor}')

    def test_all_glossary_links_have_targets(self):
        """Every internal #anchor link in the wiki must point to an existing id."""
        import re
        html = self.client.get(reverse('wiki')).content.decode('utf-8')
        ids = set(re.findall(r'id="([^"]+)"', html))
        internal_links = set(re.findall(r'href="#([^"]+)"', html))
        # Alpine-bound :href and section nav are dynamic; check static links only.
        missing = {a for a in internal_links if a not in ids}
        self.assertFalse(missing, f'wiki links without target ids: {missing}')
