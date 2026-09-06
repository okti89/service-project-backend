from rest_framework.routers import SimpleRouter

from .views import QuoteViewSet


router = SimpleRouter()
router.register(r"", QuoteViewSet, basename="quote")

urlpatterns = router.urls
