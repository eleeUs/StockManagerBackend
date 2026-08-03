from django.urls import path

from .views import (
    LowStockReportView,
    MovementSummaryReportView,
    BranchActivityReportView,
)

urlpatterns = [
    path("stock/low/",                 LowStockReportView.as_view(),       name="report-stock-low"),
    path("movements/summary/",         MovementSummaryReportView.as_view(), name="report-movements-summary"),
    path("branches/<int:id>/activity/", BranchActivityReportView.as_view(), name="report-branch-activity"),
]
