from django.urls import path
from .views import BranchListCreateView, BranchDetailView

urlpatterns = [
    path("",        BranchListCreateView.as_view(), name="branch-list-create"),
    path("<int:pk>/", BranchDetailView.as_view(),   name="branch-detail"),
]
