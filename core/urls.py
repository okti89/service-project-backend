from django.contrib import admin
from django.urls import path, include, re_path
from core.views import GlobalSearchView, privacy_policy
from django.conf import settings

from django.http import JsonResponse
from django.views.static import serve


def health_check(request):
    return JsonResponse({'status': 'ok'})

urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('privacy-policy/', privacy_policy, name='privacy-policy'),
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/accounting/', include('accounting.urls')),
    path('api/config/', include('config.urls')),
    path('api/customers/', include('customers.urls')),
    path("api/hr/", include("hr.urls")),
    path('api/notifications/', include('notifications.urls')),
    path('api/reports/', include('reports.urls')),
    path('api/services/', include('services.urls')),
    path('api/technicians/', include('technicians.urls')),
    path('api/products/', include('products.urls')),
    path("api/global-search/", GlobalSearchView.as_view(), name="global-search"),
    path("api/maps/", include("maps.urls")),
    path("api/feedback/", include("feedback.urls")),

]
if settings.SERVE_MEDIA_WITH_DJANGO and settings.MEDIA_URL.startswith('/media/'):
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
