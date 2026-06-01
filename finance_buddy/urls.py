from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import AssetViewSet, PriceDataViewSet, NewsArticleViewSet, DashboardView

router = DefaultRouter()
router.register(r'assets', AssetViewSet, basename='asset')
router.register(r'prices', PriceDataViewSet, basename='price')
router.register(r'news', NewsArticleViewSet, basename='news')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('', DashboardView.as_view(), name='dashboard'),
]
