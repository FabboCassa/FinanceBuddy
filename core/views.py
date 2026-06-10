from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.generic import TemplateView
from django.utils import timezone
import datetime

from core.models import (
    Asset, PriceData, NewsArticle, Alert, AssetScore,
    Portfolio, PaperTrade, PortfolioSnapshot,
)
from core.serializers import (
    AssetSerializer, PriceDataSerializer, NewsArticleSerializer, AlertSerializer,
    AssetScoreSerializer, PaperTradeSerializer,
)
from core import indicators, correlation, backtest, constants


class AssetViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows assets to be viewed, created, or deleted.
    """
    queryset = Asset.objects.all().order_by('symbol')
    serializer_class = AssetSerializer
    # Symbols like "000333.SZ" contain a dot: DRF's default lookup regex
    # ([^/.]+) excludes it and 404s /api/assets/<symbol>/... detail routes.
    lookup_value_regex = r'[^/]+'

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
        params = self.request.query_params

        asset_id = params.get('asset')
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)

        # Phase 4: relevance filter — by exact theme category and/or relevance flag.
        category = params.get('category')
        if category:
            queryset = queryset.filter(category=category)

        relevant = params.get('relevant')
        if relevant == 'true':
            queryset = queryset.filter(is_relevant=True)
        elif relevant == 'false':
            queryset = queryset.filter(is_relevant=False)

        # Phase 4: source-quality filter — verified = premium+quality, or exact tier.
        quality = params.get('quality')
        if quality == 'verified':
            queryset = queryset.filter(source_tier__in=constants.VERIFIED_SOURCE_TIERS)
        elif quality in (constants.SOURCE_TIER_PREMIUM, constants.SOURCE_TIER_QUALITY,
                         constants.SOURCE_TIER_UNVERIFIED):
            queryset = queryset.filter(source_tier=quality)

        return queryset


class IndicatorsView(APIView):
    """
    Phase 2 endpoint: technical-analysis indicators for a single asset.

    GET /api/indicators/?asset=<symbol> → chart-ready EMA/RSI/MACD series
    computed server-side from the stored close prices (ordered by timestamp).
    """

    def get(self, request):
        symbol = request.query_params.get('asset')
        if not symbol:
            return Response(
                {'detail': "Query param 'asset' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = (PriceData.objects
                .filter(asset_id=symbol)
                .order_by('timestamp')
                .values_list('timestamp', 'close'))
        if not rows:
            return Response({
                'ema20': [], 'ema50': [], 'ema200': [],
                'rsi': [], 'macd': [], 'macd_signal': [], 'macd_hist': [],
            })

        timestamps = [r[0] for r in rows]
        closes = [r[1] for r in rows]
        return Response(indicators.compute_indicators(timestamps, closes))


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint exposing fired sentiment alerts (most recent first).
    Optional filtering by 'asset' (symbol).
    """
    serializer_class = AlertSerializer

    def get_queryset(self):
        queryset = Alert.objects.all().order_by('-created_at')
        asset_id = self.request.query_params.get('asset')
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
        return queryset


class RankingView(APIView):
    """
    Phase 4 endpoint: the composite "Top Opportunità" leaderboard.

    GET /api/ranking/?limit=20&order=top|bottom → ranked assets with their
    score (0–100) and the normalized components (sentiment, sentiment momentum,
    technical, price momentum), read from the precomputed AssetScore snapshot.
    """

    def get(self, request):
        try:
            limit = max(1, min(100, int(request.query_params.get('limit', 20))))
        except (TypeError, ValueError):
            limit = 20

        order = request.query_params.get('order', 'top')
        queryset = AssetScore.objects.select_related('asset')
        queryset = queryset.order_by('score' if order == 'bottom' else '-score')[:limit]
        return Response(AssetScoreSerializer(queryset, many=True).data)


class MarketSummaryView(APIView):
    """
    Home/overview endpoint: market-wide snapshot for the dashboard landing view.

    GET /api/summary/ → tracked-asset count, news volume in the last
    SUMMARY_NEWS_HOURS, average sentiment and alert count over the last
    SUMMARY_WINDOW_DAYS, plus the current best/worst composite scores.
    """

    def get(self, request):
        from django.db.models import Avg

        now = timezone.now()
        news_since = now - datetime.timedelta(hours=constants.SUMMARY_NEWS_HOURS)
        window_since = now - datetime.timedelta(days=constants.SUMMARY_WINDOW_DAYS)

        avg_sentiment = (
            NewsArticle.objects
            .filter(timestamp__gte=window_since, sentiment_score__isnull=False)
            .aggregate(v=Avg('sentiment_score'))['v']
        )
        best = AssetScore.objects.order_by('-score').first()
        worst = AssetScore.objects.order_by('score').first()

        return Response({
            'assets_tracked': Asset.objects.count(),
            'news_24h': NewsArticle.objects.filter(timestamp__gte=news_since).count(),
            'avg_sentiment_7d': avg_sentiment,
            'alerts_7d': Alert.objects.filter(created_at__gte=window_since).count(),
            'best': {'symbol': best.asset_id, 'score': best.score} if best else None,
            'worst': {'symbol': worst.asset_id, 'score': worst.score} if worst else None,
        })


class CorrelationView(APIView):
    """
    Phase 2 endpoint: sentiment ↔ forward-return correlation for one asset.

    GET /api/correlation/?asset=<symbol> → Pearson/Spearman coefficients and
    mean forward return at 1/3/7-day horizons, computed server-side.
    """

    def get(self, request):
        symbol = request.query_params.get('asset')
        if not symbol:
            return Response(
                {'detail': "Query param 'asset' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        news = list(NewsArticle.objects
                    .filter(asset_id=symbol, sentiment_score__isnull=False)
                    .values('timestamp', 'sentiment_score'))
        prices = (PriceData.objects
                  .filter(asset_id=symbol)
                  .order_by('timestamp')
                  .values_list('timestamp', 'close'))
        return Response(correlation.compute_sentiment_correlation(news, prices))


def _clamped_float(params, key, default, lo, hi):
    """Parse a float query param, falling back to `default`, clamped to [lo, hi]."""
    raw = params.get(key)
    if raw is None or raw == '':
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class BacktestView(APIView):
    """
    Phase 3 endpoint: backtest the sentiment sandbox strategy for one asset.

    GET /api/backtest/?asset=<symbol>&buy_threshold=&sell_threshold=
        &stop_loss_pct=&sentiment_window_days=&initial_capital=

    Runs the long-only rolling-sentiment strategy over the stored daily history
    and returns equity curve, trades, buy/sell signals, and risk metrics
    (Sharpe, Sortino, max drawdown, win rate, alpha vs buy & hold). Tunable
    params are validated and clamped to sane bounds; omitted ones use the
    constants.py defaults.
    """

    def get(self, request):
        symbol = request.query_params.get('asset')
        if not symbol:
            return Response(
                {'detail': "Query param 'asset' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        p = request.query_params
        buy = _clamped_float(p, 'buy_threshold', constants.BACKTEST_BUY_THRESHOLD, -1.0, 1.0)
        sell = _clamped_float(p, 'sell_threshold', constants.BACKTEST_SELL_THRESHOLD, -1.0, 1.0)
        stop = _clamped_float(p, 'stop_loss_pct', constants.BACKTEST_STOP_LOSS_PCT, 0.0, 1.0)
        window = int(_clamped_float(p, 'sentiment_window_days',
                                    constants.BACKTEST_SENTIMENT_WINDOW_DAYS, 1, 365))
        capital = _clamped_float(p, 'initial_capital',
                                 constants.BACKTEST_INITIAL_CAPITAL, 1.0, 1e9)

        prices = (PriceData.objects
                  .filter(asset_id=symbol)
                  .order_by('timestamp')
                  .values_list('timestamp', 'close'))
        news = list(NewsArticle.objects
                    .filter(asset_id=symbol, sentiment_score__isnull=False)
                    .values('timestamp', 'sentiment_score'))

        result = backtest.run_backtest(
            prices, news,
            buy_threshold=buy, sell_threshold=sell, stop_loss_pct=stop,
            sentiment_window_days=window, initial_capital=capital,
        )
        return Response(result)


class PortfolioView(APIView):
    """
    Phase 5 endpoint: the virtual paper-trading portfolio snapshot.

    GET /api/portfolio/ → cash, open positions marked to the latest close
    (market value + unrealized P&L), realized P&L, total equity and return vs.
    the initial capital, performance metrics, and the most recent virtual trades.
    The same payload is pushed live over WebSocket (see `core.realtime`). Read-only;
    the `run_paper_trading` task is what actually opens/closes positions.
    """

    def get(self, request):
        from core.portfolio import get_portfolio_payload
        return Response(get_portfolio_payload())


class PortfolioHistoryView(APIView):
    """
    Phase 5 endpoint: the paper-portfolio equity curve.

    GET /api/portfolio/history/ → chronological mark-to-market snapshots
    (total value / cash / holdings) for the equity-curve chart.
    """

    def get(self, request):
        from core.tasks import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        snapshots = portfolio.snapshots.order_by('timestamp').values(
            'timestamp', 'cash', 'holdings_value', 'total_value')
        return Response([
            {
                'timestamp': s['timestamp'],
                'cash': round(s['cash'], 2),
                'holdings_value': round(s['holdings_value'], 2),
                'total_value': round(s['total_value'], 2),
            }
            for s in snapshots
        ])


class DashboardView(TemplateView):
    """
    Serves the premium single-page dashboard HTML template.
    """
    template_name = 'core/dashboard.html'


class WikiView(TemplateView):
    """
    Phase 6: educational Knowledge Base / wiki.

    Serves the static `/wiki/` page that explains — in plain Italian, with the
    standard English term alongside, numeric examples and KaTeX formulas —
    every concept used elsewhere in the dashboard. Deep-linkable anchors
    (e.g. /wiki/#sharpe) are the targets of the dashboard's contextual ℹ︎ icons.
    """
    template_name = 'core/wiki.html'
