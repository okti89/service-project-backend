from django.contrib import admin
from django.urls import path, include
from core.views import GlobalSearchView

urlpatterns = [
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