from django.urls import path

from maps import views

app_name = "maps"

urlpatterns = [
    path("geocode/", views.maps_geocode, name="geocode"),
    path("directions/", views.maps_directions, name="directions"),
    path("places/autocomplete/", views.maps_places_autocomplete, name="places-autocomplete"),
    path("distance-matrix/", views.maps_distance_matrix, name="distance-matrix"),
    path("static-map/", views.maps_static_map_url, name="static-map"),
    path("quota/", views.maps_quota, name="quota"),
]
