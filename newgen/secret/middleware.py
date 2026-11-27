"""Privacy middleware for the anonymous chat.

The product promise is that the app never stores or exposes identifying data
against an anonymous person's messages.  The database models no longer have
IP/user-agent columns, and this middleware removes the values from the request
before any view can accidentally log or persist them.

Server-level access logs (Daphne/gunicorn) are outside the application and can
still contain the connecting address.  Keep those logs short-lived on the host
if that matters to your deployment.
"""


class AnonymityMiddleware:
    """Strip network identifiers from request.META early in the chain."""

    IDENTIFYING_KEYS = (
        "REMOTE_ADDR",
        "REMOTE_HOST",
        "HTTP_USER_AGENT",
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_REAL_IP",
        "HTTP_CF_CONNECTING_IP",
        "HTTP_TRUE_CLIENT_IP",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        for key in self.IDENTIFYING_KEYS:
            request.META.pop(key, None)
        return self.get_response(request)
