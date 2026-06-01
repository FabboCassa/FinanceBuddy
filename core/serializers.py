from rest_framework import serializers
from core.models import Asset, PriceData, NewsArticle, Alert


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = '__all__'


class PriceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceData
        fields = ['id', 'timestamp', 'open', 'high', 'low', 'close', 'volume']


class NewsArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsArticle
        fields = [
            'id', 'timestamp', 'title', 'source', 'url',
            'extracted_text', 'sentiment_score', 'sentiment_label'
        ]


class AlertSerializer(serializers.ModelSerializer):
    asset_symbol = serializers.CharField(source='asset.symbol', read_only=True)

    class Meta:
        model = Alert
        fields = [
            'id', 'asset_symbol', 'level', 'avg_sentiment',
            'article_count', 'message', 'created_at',
        ]
