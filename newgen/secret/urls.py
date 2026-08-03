from django.urls import path
from . import views

urlpatterns = [

    path('', views.leader_directory, name='directory'),
    path('inbox/', views.stranger_inbox, name='stranger_inbox'),

    # Takes a LEADER id, not a conversation id. chat_room() does
    # get_or_create(leader=..., anonymous=...) internally, so linking to
    # this with {% url 'chat' conv.leader.id %} correctly resumes an
    # existing conversation with that leader instead of starting a new one.
    path('chat/<uuid:leader_id>/', views.chat_room, name='chat'),

    # Fallback HTTP send endpoint (only needed if something still posts here
    # instead of going through the WebSocket in consumers.py — remove if unused).
    path('chat/<uuid:conv_id>/send/', views.send_message, name='send_message'),

    path('leader/signin/', views.leader_signin, name='signin'),
    path('leader/inbox/', views.leader_inbox, name='leader_inbox'),
    path('leader/chat/<uuid:conv_id>/', views.leader_chat, name='leader_chat'),
    path('leader/logout/', views.leader_logout, name='logout'),
]