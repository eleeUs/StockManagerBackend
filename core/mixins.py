from django.db.models import Q


class BranchScopeQuerysetMixin:
    """
    Restricts the queryset to the user's branch when the user is a seller.
    Admins bypass this filter and see all data.

    Default behavior: filters by a single FK field named `branch`.
    Override `get_branch_q(user)` in subclasses where the branch filter
    involves multiple fields or an OR condition (e.g. movement history,
    where a seller should see both outgoing and incoming movements).

    Usage — simple case (single branch FK):
        class StockListView(BranchScopeQuerysetMixin, generics.ListAPIView):
            ...  # no override needed, branch_field default works

    Usage — OR case (movements):
        class MovementListView(BranchScopeQuerysetMixin, generics.ListAPIView):
            def get_branch_q(self, user):
                return (
                    Q(source_branch=user.branch) |
                    Q(destination_branch=user.branch)
                )

    IMPORTANT: This mixin only filters READ access. Write-access restrictions
    (e.g. a seller attempting a sale on another branch's stock) are enforced
    in the view's post() method and in the service layer.
    """

    branch_field = "branch"

    def get_branch_q(self, user) -> Q:
        """
        Returns the Q object used to filter the queryset for a seller.
        Override this in views where the default single-field filter is
        insufficient.
        """
        return Q(**{self.branch_field: user.branch})

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user

        if user.is_seller:
            qs = qs.filter(self.get_branch_q(user))

        return qs
