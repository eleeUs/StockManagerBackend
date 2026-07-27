from django.urls import path

from apps.stock.views import StockListView, StockByBranchView
from .views import (
    MovementListView,
    IngresoView,
    VentaView,
    TransferenciaView,
    ConfirmTransferView,
    CancelTransferView,
    AjusteView,
    DevolucionView,
    DonacionView,
    ReverseMovementView,
)

urlpatterns = [
    # -------------------------------------------------------------------
    # Stock (read-only)
    # -------------------------------------------------------------------
    path("stock/",                                    StockListView.as_view(),      name="stock-list"),
    path("stock/product/<int:product_id>/by-branch/", StockByBranchView.as_view(),  name="stock-by-branch"),

    # -------------------------------------------------------------------
    # Movement history (read-only, cursor-paginated)
    # -------------------------------------------------------------------
    path("movements/",                                MovementListView.as_view(),    name="movement-list"),

    # -------------------------------------------------------------------
    # Movement creation — one endpoint per type
    # -------------------------------------------------------------------
    path("movements/ingreso/",                        IngresoView.as_view(),         name="movement-ingreso"),
    path("movements/venta/",                          VentaView.as_view(),           name="movement-venta"),
    path("movements/ajuste/",                         AjusteView.as_view(),          name="movement-ajuste"),
    path("movements/devolucion/",                     DevolucionView.as_view(),      name="movement-devolucion"),
    path("movements/donacion/",                       DonacionView.as_view(),        name="movement-donacion"),

    # Transfer — creation + two-step actions
    path("movements/transferencia/",                  TransferenciaView.as_view(),   name="movement-transferencia"),
    path("movements/transferencia/<int:pk>/confirm/", ConfirmTransferView.as_view(),  name="transfer-confirm"),
    path("movements/transferencia/<int:pk>/cancel/",  CancelTransferView.as_view(),   name="transfer-cancel"),

    # Reversal — works on any confirmed movement type
    path("movements/<int:pk>/reverse/",               ReverseMovementView.as_view(),  name="movement-reverse"),
]
