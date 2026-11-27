import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.sessions import SessionMiddlewareStack
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newgen.settings")

django_asgi_app = get_asgi_application()

from secret import routing  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # The app uses its own session-based leader/device identity, so the
        # session stack (not Django auth) is all the websocket layer needs.
        "websocket": SessionMiddlewareStack(
            URLRouter(routing.websocket_urlpatterns)
        ),
    }
)