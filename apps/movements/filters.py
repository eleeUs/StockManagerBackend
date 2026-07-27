import django_filters
from django.db.models import Q
from .models import StockMovement, MovementType, MovementStatus


class StockMovementFilter(django_filters.FilterSet):
    """
    Filters for GET /api/v1/movements/
    All filters are optional and combinable.
    """
    date_from     = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to       = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")
    movement_type = django_filters.ChoiceFilter(choices=MovementType.choices)
    status        = django_filters.ChoiceFilter(choices=MovementStatus.choices)
    product       = django_filters.NumberFilter(field_name="product_id")
    source_branch = django_filters.NumberFilter(field_name="source_branch_id")
    dest_branch   = django_filters.NumberFilter(field_name="destination_branch_id")
    created_by    = django_filters.NumberFilter(field_name="created_by_id")

    # Matches movements involving a branch as either source or destination
    any_branch = django_filters.NumberFilter(method="filter_any_branch")

    class Meta:
        model  = StockMovement
        fields = [
            "movement_type",
            "status",
            "product",
            "source_branch",
            "dest_branch",
            "created_by",
        ]

    def filter_any_branch(self, queryset, name, value):
        return queryset.filter(
            Q(source_branch_id=value) | Q(destination_branch_id=value)
        )
