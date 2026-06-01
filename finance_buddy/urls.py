from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    AssetViewSet, PriceDataViewSet, NewsArticleViewSet, AlertViewSet,
    IndicatorsView, CorrelationView, BacktestView, DashboardView,
)

router = DefaultRouter()
router.register(r'assets', AssetViewSet, basename='asset')
router.register(r'prices', PriceDataViewSet, basename='price')
router.register(r'news', NewsArticleViewSet, basename='news')
router.register(r'alerts', AlertViewSet, basename='alert')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/indicators/', IndicatorsView.as_view(), name='indicators'),
    path('api/correlation/', CorrelationView.as_view(), name='correlation'),
    path('api/backtest/', BacktestView.as_view(), name='backtest'),
    path('api/', include(router.urls)),
    path('', DashboardView.as_view(), name='dashboard'),
]
