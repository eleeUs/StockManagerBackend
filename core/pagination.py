from rest_framework.pagination import PageNumberPagination, CursorPagination


class StandardPagination(PageNumberPagination):
    """
    Default pagination for most endpoints.
    Supports ?page=N and ?page_size=N query params.
    """
    page_size            = 20
    page_size_query_param = "page_size"
    max_page_size        = 100


class MovementCursorPagination(CursorPagination):
    """
    Cursor-based pagination for the movement history endpoint.

    Ordering: ("-created_at", "id") — combined for two reasons:
      1. created_at provides temporal semantics to the cursor, making it
         meaningful for debugging ("from this timestamp onward").
      2. id breaks ties when two movements share the same created_at
         timestamp (possible under concurrent load). Without the tiebreaker,
         a record could appear in two pages or be skipped entirely.
         id is strictly monotonic in PostgreSQL, so (timestamp, id) is
         always a unique, stable cursor position.

    CursorPagination is preferred over PageNumberPagination for this table
    because it uses a WHERE clause on indexed columns instead of OFFSET N.
    OFFSET degrades linearly as the table grows (scanning N rows to skip them).
    A cursor-based WHERE clause is O(log N) regardless of table size.
    """
    page_size             = 50
    page_size_query_param = "page_size"
    max_page_size         = 200
    ordering              = ("-created_at", "id")
