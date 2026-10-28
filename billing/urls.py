from django.urls import path
from . import views
urlpatterns = [path('apple/profile/', views.profile), path('apple/verify/', views.verify),
               path('apple/notifications/', views.notifications)]
