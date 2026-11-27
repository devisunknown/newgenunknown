from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/chat/(?P<conv_id>[0-9a-f-]{36})/(?P<role>anon|leader)/$",
        consumers.ChatConsumer.as_asgi(),
    ),
    re_path(
        r"ws/leader/inbox/$",
        consumers.LeaderInboxConsumer.as_asgi(),
    ),
]
