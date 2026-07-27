from rest_framework.pagination import PageNumberPagination, CursorPagination


class StandardPagination(PageNumberPagination):
    """
    Default pagination for most endpoints.
    Supports ?page=N and ?page_size=N query params.
    """
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MovementCursorPagination(CursorPagination):
    """
    Cursor-based pagination for the movement history endpoint.
    More efficient than offset pagination on large tables because it
    uses a WHERE clause on an indexed column instead of OFFSET N.
    Use this for any append-only historical log.
    """
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = "-created_at"
