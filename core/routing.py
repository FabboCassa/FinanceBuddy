"""WebSocket URL routing (Phase 5 real-time)."""
from django.urls import path

from core.consumers import PortfolioConsumer

websocket_urlpatterns = [
    path('ws/portfolio/', PortfolioConsumer.as_asgi()),
]
