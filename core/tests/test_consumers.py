"""WebSocket consumer tests (Phase 5 real-time).

Uses the in-memory channel layer so no Redis is needed, and TransactionTestCase
so the consumer's threaded DB access (database_sync_to_async) sees committed rows.
"""
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from core.realtime import PORTFOLIO_GROUP
from core.routing import websocket_urlpatterns

INMEM = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=INMEM)
class PortfolioConsumerTests(TransactionTestCase):
    async def test_connect_snapshot_then_relays_broadcast(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), '/ws/portfolio/')
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # On connect the consumer pushes an initial snapshot of the portfolio.
        first = await communicator.receive_json_from()
        self.assertEqual(first['type'], 'portfolio.update')
        self.assertIn('total_value', first['payload'])

        # Any later group broadcast is forwarded verbatim to the client.
        await get_channel_layer().group_send(
            PORTFOLIO_GROUP,
            {'type': 'portfolio.update', 'payload': {'total_value': 12345}})
        relayed = await communicator.receive_json_from()
        self.assertEqual(relayed['payload']['total_value'], 12345)

        await communicator.disconnect()

    async def test_client_messages_are_ignored(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), '/ws/portfolio/')
        await communicator.connect()
        await communicator.receive_json_from()  # drain the initial snapshot

        # The stream is read-only: sending something must not error or reply.
        await communicator.send_json_to({'hello': 'world'})
        self.assertTrue(await communicator.receive_nothing())

        await communicator.disconnect()
