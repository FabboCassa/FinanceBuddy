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
    the initial capital, plus the most recent virtual trades. Read-only; the
    `run_paper_trading` task is what actually opens/closes positions.
    """
    RECENT_TRADES = 25

    def get(self, request):
        from django.db.models import Sum
        from core.tasks import get_or_create_default_portfolio, _latest_closes

        portfolio = get_or_create_default_portfolio()
        closes = _latest_closes()

        positions = []
        holdings_value = 0.0
        for pos in portfolio.positions.select_related('asset'):
            price = closes.get(pos.asset_id)
            market_value = (pos.quantity * price) if price is not None else None
            cost_basis = pos.quantity * pos.avg_entry_price
            if market_value is not None:
                holdings_value += market_value
                pnl = market_value - cost_basis
                pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0.0
            else:
                pnl = pnl_pct = None
            positions.append({
                'symbol': pos.asset_id,
                'name': pos.asset.name,
                'quantity': round(pos.quantity, 6),
                'avg_entry_price': round(pos.avg_entry_price, 4),
                'current_price': round(price, 4) if price is not None else None,
                'market_value': round(market_value, 2) if market_value is not None else None,
                'unrealized_pnl': round(pnl, 2) if pnl is not None else None,
                'unrealized_pnl_pct': round(pnl_pct, 2) if pnl_pct is not None else None,
            })

        total_value = portfolio.cash + holdings_value
        realized = portfolio.trades.aggregate(s=Sum('realized_pnl'))['s'] or 0.0
        initial = portfolio.initial_capital or 0.0
        total_return_pct = ((total_value / initial - 1) * 100) if initial else 0.0
        recent = portfolio.trades.all()[:self.RECENT_TRADES]

        performance = self._performance(portfolio, closes, total_value, total_return_pct)

        return Response({
            'name': portfolio.name,
            'initial_capital': round(initial, 2),
            'cash': round(portfolio.cash, 2),
            'holdings_value': round(holdings_value, 2),
            'total_value': round(total_value, 2),
            'total_return_pct': round(total_return_pct, 2),
            'realized_pnl': round(realized, 2),
            'num_positions': len(positions),
            'positions': sorted(positions, key=lambda p: p['market_value'] or 0, reverse=True),
            'recent_trades': PaperTradeSerializer(recent, many=True).data,
            'performance': performance,
            'updated_at': portfolio.updated_at,
        })

    def _performance(self, portfolio, closes, total_value, total_return_pct):
        """Risk/return metrics for the live portfolio, shaped like a backtest's.

        Reuses ``core.metrics`` so the paper run reports the same Sharpe/Sortino/
        drawdown/win-rate as a backtest of the same strategy. The benchmark is an
        equal-weight buy-&-hold of the names the bot has actually traded over the
        portfolio's lifetime ("what if you'd just held these instead of timing
        them"); ``alpha`` is the bot's edge over that. Values are ``None`` until
        there's enough history (≥2 snapshots, ≥1 closed trade) to be meaningful.
        """
        from core import metrics

        snapshot_values = list(
            portfolio.snapshots.order_by('timestamp').values_list('total_value', flat=True))
        realized_pnls = list(
            portfolio.trades.filter(side='SELL').values_list('realized_pnl', flat=True))

        risk = metrics.equity_curve_metrics(snapshot_values) or {}

        first_ts = (portfolio.snapshots.order_by('timestamp')
                    .values_list('timestamp', flat=True).first())
        buy_hold_pct = None
        if first_ts:
            pairs = []
            for symbol in portfolio.trades.values_list('asset_id', flat=True).distinct():
                first_close = (PriceData.objects
                               .filter(asset_id=symbol, timestamp__gte=first_ts)
                               .order_by('timestamp').values_list('close', flat=True).first())
                pairs.append((first_close, closes.get(symbol)))
            buy_hold_pct = metrics.buy_hold_return_pct(pairs)

        alpha_pct = (round(total_return_pct - buy_hold_pct, 2)
                     if buy_hold_pct is not None else None)

        return {
            'sharpe_ratio': risk.get('sharpe_ratio'),
            'sortino_ratio': risk.get('sortino_ratio'),
            'max_drawdown_pct': risk.get('max_drawdown_pct'),
            'win_rate_pct': metrics.win_rate(realized_pnls),
            'num_closed_trades': sum(1 for p in realized_pnls if p is not None),
            'buy_hold_return_pct': round(buy_hold_pct, 2) if buy_hold_pct is not None else None,
            'alpha_pct': alpha_pct,
        }


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
