import time
import logging
from django.db import connection

logger = logging.getLogger('db_diagnostics')


class QueryCountMiddleware:
    """
    Drop this in any Django project to see, per request, how many DB queries
    ran and how long they took in total. Add it to MIDDLEWARE (dev/staging
    only — remove or gate behind DEBUG before going to real production, since
    it adds overhead and connection.queries only populates when DEBUG=True
    or you force it, see note below).

    Usage in settings.py:
        MIDDLEWARE = [
            ...,
            'yourapp.middleware.QueryCountMiddleware',
        ]

    Output shows in your console/logs like:
        [DB] GET /leader/inbox/  ->  14 queries in 187.32ms
    Anything over ~10-15 queries on a normal page, or over ~200ms total DB
    time, is worth investigating with select_related/prefetch_related or an
    index — that's your actual signal instead of a guess.
    """

    SLOW_QUERY_THRESHOLD_MS = 50   # flag any single query slower than this
    HIGH_QUERY_COUNT = 15          # flag any request making more queries than this

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_queries = len(connection.queries)
        start_time = time.monotonic()

        response = self.get_response(request)

        total_time_ms = (time.monotonic() - start_time) * 1000
        query_count = len(connection.queries) - start_queries

        # connection.queries only populates when DEBUG=True. If you need
        # this on a non-DEBUG environment, temporarily set
        # connection.force_debug_cursor = True at the top of __call__.
        db_time_ms = sum(float(q['time']) * 1000 for q in connection.queries[start_queries:]) if connection.queries else 0

        flag = ""
        if query_count > self.HIGH_QUERY_COUNT:
            flag = f"  <-- HIGH QUERY COUNT ({query_count})"

        logger.info(
            f"[DB] {request.method} {request.path} -> "
            f"{query_count} queries, {db_time_ms:.2f}ms DB time, "
            f"{total_time_ms:.2f}ms total{flag}"
        )

        # Log individual slow queries so you know exactly which one to fix
        if connection.queries:
            for q in connection.queries[start_queries:]:
                q_time_ms = float(q['time']) * 1000
                if q_time_ms > self.SLOW_QUERY_THRESHOLD_MS:
                    logger.warning(f"[DB] SLOW QUERY ({q_time_ms:.2f}ms): {q['sql'][:300]}")

        return response