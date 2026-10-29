from django.urls import path
from . import views
urlpatterns = [path('revenuecat/profile/', views.profile), path('revenuecat/sync/', views.sync),
               path('revenuecat/webhook/', views.webhook)]
