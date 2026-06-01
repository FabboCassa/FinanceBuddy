from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.views.generic import TemplateView
from django.utils import timezone
import datetime

from core.models import Asset, PriceData, NewsArticle
from core.serializers import AssetSerializer, PriceDataSerializer, NewsArticleSerializer


class AssetViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows assets to be viewed, created, or deleted.
    """
    queryset = Asset.objects.all().order_by('symbol')
    serializer_class = AssetSerializer

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """
        Manually trigger a sync of price history and news for a specific asset.
        """
        asset = self.get_object()
        
        # Trigger Celery background tasks
        from core.tasks import fetch_market_data, fetch_news
        fetch_market_data.delay()
        fetch_news.delay()
        
        return Response(
            {'status': f'Sync tasks successfully dispatched for {asset.symbol}. Data will appear in few seconds.'},
            status=status.HTTP_202_ACCEPTED
        )


class PriceDataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows price data to be queried.
    Supports filtering by 'asset' (symbol) and date ranges.
    """
    serializer_class = PriceDataSerializer

    def get_queryset(self):
        queryset = PriceData.objects.all().order_by('timestamp')
        asset_id = self.request.query_params.get('asset')
        
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
            
        start_date = self.request.query_params.get('start_date')
        if start_date:
            try:
                # Support YYYY-MM-DD
                parsed_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
                parsed_date = timezone.make_aware(parsed_date, timezone.get_current_timezone())
                queryset = queryset.filter(timestamp__gte=parsed_date)
            except ValueError:
                pass
                
        end_date = self.request.query_params.get('end_date')
        if end_date:
            try:
                parsed_date = datetime.datetime.strptime(end_date, '%Y-%m-%d')
                # Make end of day
                parsed_date = parsed_date.replace(hour=23, minute=59, second=59)
                parsed_date = timezone.make_aware(parsed_date, timezone.get_current_timezone())
                queryset = queryset.filter(timestamp__lte=parsed_date)
            except ValueError:
                pass
                
        return queryset


class NewsArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows news articles to be queried.
    Supports filtering by 'asset' (symbol).
    """
    serializer_class = NewsArticleSerializer

    def get_queryset(self):
        queryset = NewsArticle.objects.all().order_by('-timestamp')
        asset_id = self.request.query_params.get('asset')
        
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
            
        return queryset


class DashboardView(TemplateView):
    """
    Serves the premium single-page dashboard HTML template.
    """
    template_name = 'core/dashboard.html'
