from rest_framework import serializers
from core.models import (
    Asset, PriceData, NewsArticle, Alert, AssetScore, PaperTrade,
)
from core import constants


class AssetSerializer(serializers.ModelSerializer):
    # Convenience for the dashboard "earnings imminenti" badge: days from today
    # to next_earnings_date (negative = stale past date awaiting refresh).
    days_to_earnings = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = '__all__'

    def get_days_to_earnings(self, obj):
        if obj.next_earnings_date is None:
            return None
        from django.utils import timezone
        return (obj.next_earnings_date - timezone.localdate()).days


class PriceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceData
        fields = ['id', 'timestamp', 'open', 'high', 'low', 'close', 'volume']


class NewsArticleSerializer(serializers.ModelSerializer):
    category_label = serializers.SerializerMethodField()
    source_tier_label = serializers.SerializerMethodField()
    source_country = serializers.SerializerMethodField()
    source_language = serializers.SerializerMethodField()

    class Meta:
        model = NewsArticle
        fields = [
            'id', 'timestamp', 'title', 'source', 'url',
            'extracted_text', 'sentiment_score', 'sentiment_label',
            'category', 'category_label', 'is_relevant', 'forward_impact',
            'source_tier', 'source_tier_label', 'source_country', 'source_language',
        ]

    def get_category_label(self, obj):
        """Localized label for the theme category (None when not yet categorized)."""
        return constants.NEWS_CATEGORY_LABELS.get(obj.category)

    def get_source_tier_label(self, obj):
        return constants.SOURCE_TIER_LABELS.get(obj.source_tier)

    def get_source_country(self, obj):
        from core import sources
        return sources.source_meta(obj.source)[2]

    def get_source_language(self, obj):
        from core import sources
        return sources.source_meta(obj.source)[3]


class AssetScoreSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source='asset_id', read_only=True)
    name = serializers.CharField(source='asset.name', read_only=True)
    asset_type = serializers.CharField(source='asset.asset_type', read_only=True)

    class Meta:
        model = AssetScore
        fields = [
            'symbol', 'name', 'asset_type', 'score', 'rank',
            'components', 'n_articles', 'low_news', 'updated_at',
        ]


class PaperTradeSerializer(serializers.ModelSerializer):
    """A single executed virtual order (Phase 5)."""
    symbol = serializers.CharField(source='asset_id', read_only=True)
    name = serializers.CharField(source='asset.name', read_only=True)

    class Meta:
        model = PaperTrade
        fields = [
            'id', 'symbol', 'name', 'side', 'quantity', 'price',
            'value', 'reason', 'realized_pnl', 'executed_at',
        ]


class AlertSerializer(serializers.ModelSerializer):
    asset_symbol = serializers.CharField(source='asset.symbol', read_only=True)

    class Meta:
        model = Alert
        fields = [
            'id', 'asset_symbol', 'level', 'avg_sentiment',
            'article_count', 'message', 'created_at',
        ]
