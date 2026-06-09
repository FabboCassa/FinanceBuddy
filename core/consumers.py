"""WebSocket consumers (Phase 5 real-time).

``PortfolioConsumer`` streams the virtual paper portfolio to the dashboard: it
joins the broadcast group, sends an initial snapshot on connect, then relays each
``portfolio.update`` the `core.realtime` broadcaster fans out. Read-only — the bot
is the only writer, so any inbound client message is ignored.
"""
from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from core.realtime import PORTFOLIO_GROUP, json_safe


class PortfolioConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(PORTFOLIO_GROUP, self.channel_name)
        await self.accept()
        payload = await self._snapshot()
        if payload is not None:
            await self.send_json({'type': 'portfolio.update', 'payload': payload})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(PORTFOLIO_GROUP, self.channel_name)

    async def receive_json(self, content, **kwargs):
        pass  # read-only stream

    async def portfolio_update(self, event):
        """Group handler for a `portfolio.update` message → forward to the client."""
        await self.send_json({'type': 'portfolio.update', 'payload': event['payload']})

    @database_sync_to_async
    def _snapshot(self):
        from core.portfolio import get_portfolio_payload
        try:
            return json_safe(get_portfolio_payload())
        except Exception:
            return None
