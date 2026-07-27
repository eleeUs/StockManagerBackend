from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """
    Grants access only to users with the 'admin' role.
    Use on any endpoint that modifies data across branches
    or manages users and products.
    """
    message = "Only administrators can perform this action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )


class IsSeller(BasePermission):
    """
    Grants access only to users with the 'seller' role.
    Rarely used alone — most endpoints allow both roles.
    """
    message = "Only sellers can perform this action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "seller"
        )


class IsAdminOrSeller(BasePermission):
    """
    Grants access to any authenticated user regardless of role.
    Effectively the same as IsAuthenticated but semantically
    explicit about the two allowed roles.
    """
    message = "Authentication required."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ("admin", "seller")
        )


class CanAccessBranch(BasePermission):
    """
    Object-level permission.
    - Admins can access any branch.
    - Sellers can only access their assigned branch.

    The object passed to has_object_permission must have
    a `branch` attribute or a `source_branch` attribute.

    IMPORTANT: This only controls write access to objects.
    Read access filtering (sellers only see their branch data)
    must be implemented in get_queryset(), not here.
    """
    message = "You do not have permission to access this branch."

    def has_object_permission(self, request, view, obj):
        if request.user.role == "admin":
            return True

        # Resolve the branch from the object — supports both
        # direct branch references and movement-style references.
        obj_branch = getattr(obj, "branch_id", None) or getattr(obj, "source_branch_id", None)
        return obj_branch == request.user.branch_id
