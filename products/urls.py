from django.urls import path
from .views import (
    ProductCategoryListCreateView, ProductCategoryDetailView,
    ProductListCreateView, ProductDetailView,
    StockMovementListCreateView, StockMovementDetailView
)

urlpatterns = [
    # =========================
    # CATEGORIES
    # =========================
    path('categories/', ProductCategoryListCreateView.as_view(), name='product-category-list'),
    path('categories/<uuid:pk>/', ProductCategoryDetailView.as_view(), name='product-category-detail'),

    # =========================
    # PRODUCTS
    # =========================
    path('products/', ProductListCreateView.as_view(), name='product-list'),
    path('products/<uuid:pk>/', ProductDetailView.as_view(), name='product-detail'),

    # =========================
    # STOCK MOVEMENTS
    # =========================
    path('stock-movements/', StockMovementListCreateView.as_view(), name='stock-movement-list'),
    path('stock-movements/<uuid:pk>/', StockMovementDetailView.as_view(), name='stock-movement-detail'),
]