from django.urls import path
from .views import (
    CategoryListCreateView,
    ProductListCreateView,
    ProductDetailView,
)

urlpatterns = [
    path("",                   ProductListCreateView.as_view(), name="product-list-create"),
    path("<int:pk>/",          ProductDetailView.as_view(),     name="product-detail"),
    path("categories/",        CategoryListCreateView.as_view(), name="category-list-create"),
]
