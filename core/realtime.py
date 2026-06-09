"""Real-time WebSocket fan-out for the paper portfolio (Phase 5).

The paper-trading cycle (Celery worker, sync context) calls
``broadcast_portfolio_update`` after each run; it pushes the current snapshot to
every connected dashboard via the Redis channel layer. Best-effort by design — a
missing or unreachable channel layer must never break the trading cycle.
"""
from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework.renderers import JSONRenderer

logger = logging.getLogger(__name__)

# All dashboards subscribe to this single broadcast group.
PORTFOLIO_GROUP = 'paper_trading'


def json_safe(payload):
    """Coerce a DRF/ORM payload (Decimals, OrderedDicts, …) to plain JSON types."""
    return json.loads(JSONRenderer().render(payload))


def broadcast_portfolio_update(portfolio=None):
    """Push the current portfolio snapshot to all connected dashboards.

    Swallows (and logs) any error so a channel-layer hiccup can't abort the
    paper-trading cycle that triggers it.
    """
    from core.portfolio import get_portfolio_payload

    layer = get_channel_layer()
    if layer is None:
        return
    try:
        payload = json_safe(get_portfolio_payload(portfolio))
        async_to_sync(layer.group_send)(
            PORTFOLIO_GROUP,
            {'type': 'portfolio.update', 'payload': payload},
        )
    except Exception as e:  # noqa: BLE001 — never let broadcasting break trading
        logger.warning(f"Portfolio WS broadcast skipped: {e}")
