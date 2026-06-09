"""Paper-portfolio read model (Phase 5).

Builds the full dashboard payload for the virtual portfolio — cash, marked-to-
market positions, realized/unrealized P&L, return, performance metrics and recent
trades — in one place so the REST endpoint (`PortfolioView`) and the real-time
WebSocket broadcaster (`core.realtime`) serve the *same* shape. Read-only; the
`run_paper_trading` task is what actually opens/closes positions.

Returns plain JSON-safe types (datetimes as ISO strings) so the payload can go
straight over a channel layer or a DRF response without further coercion.
"""
from __future__ import annotations

from django.db.models import Sum

from core.models import PriceData
from core.serializers import PaperTradeSerializer

RECENT_TRADES = 25


def get_portfolio_payload(portfolio=None) -> dict:
    """Assemble the complete portfolio snapshot dict for the dashboard."""
    # Lazy import: tasks imports this module's siblings, so defer to call time.
    from core.tasks import get_or_create_default_portfolio, _latest_closes

    portfolio = portfolio or get_or_create_default_portfolio()
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
    recent = portfolio.trades.all()[:RECENT_TRADES]

    return {
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
        'performance': _performance(portfolio, closes, total_value, total_return_pct),
        'updated_at': portfolio.updated_at.isoformat() if portfolio.updated_at else None,
    }


def _performance(portfolio, closes, total_value, total_return_pct) -> dict:
    """Risk/return metrics for the live portfolio, shaped like a backtest's.

    Reuses ``core.metrics`` so the paper run reports the same Sharpe/Sortino/
    drawdown/win-rate as a backtest of the same strategy. The benchmark is an
    equal-weight buy-&-hold of the names the bot has actually traded over the
    portfolio's lifetime ("what if you'd just held these instead of timing them");
    ``alpha`` is the bot's edge over that. Values are ``None`` until there's enough
    history (≥2 snapshots, ≥1 closed trade) to be meaningful.
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
