import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.sessions import SessionMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newgen.settings')

django_asgi_app = get_asgi_application()

from secret import routing  # or whatever your app is called

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': SessionMiddlewareStack(
    AuthMiddlewareStack(
        URLRouter(
            routing.websocket_urlpatterns
        )
    )
),
})