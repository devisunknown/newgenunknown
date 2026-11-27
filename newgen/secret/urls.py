from django.urls import path

from . import views


urlpatterns = [
    # Public pages. The person's own chats live at /inbox/.
    path("", views.landing, name="landing"),
    path("privacy/", views.privacy, name="privacy"),
    # Root-served so the service worker controls every page.
    path("manifest.webmanifest", views.web_manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("inbox/", views.stranger_inbox, name="directory"),
    # Anonymous problem board: anyone can post and reply without an account.
    path("anonboard/", views.anon_board, name="anon_board"),
    path(
        "anonboard/<uuid:post_id>/",
        views.anon_board_post,
        name="anon_board_post",
    ),
    path("welcome/", views.leader_directory, name="welcome"),

    # Institution rooms — the room UUID is the invitation key.
    path("chatroom/<uuid:room_id>/", views.room_entry, name="room_entry"),
    path(
        "chatroom/<uuid:room_id>/directory/",
        views.room_people,
        name="room_directory",
    ),
    path(
        "chatroom/<uuid:room_id>/directory/leaders/",
        views.room_people_data,
        name="room_people_data",
    ),
    path(
        "chatroom/<uuid:room_id>/people/",
        views.room_people,
        name="room_people",
    ),
    path(
        "chatroom/<uuid:room_id>/chat/<uuid:leader_id>/",
        views.start_chat,
        name="start_chat",
    ),

    # Legacy slug links keep working by finding the matching room.
    path("r/<slug:slug>/", views.legacy_room_entry, name="legacy_room_entry"),
    path(
        "r/<slug:slug>/directory/",
        views.legacy_room_directory,
        name="legacy_room_directory",
    ),
    path(
        "r/<slug:slug>/people/",
        views.legacy_room_directory,
        name="legacy_room_people",
    ),
    path(
        "r/<slug:slug>/chat/<uuid:leader_id>/",
        views.legacy_start_chat,
        name="legacy_start_chat",
    ),

    # Anonymous conversation
    path("c/<uuid:conv_id>/", views.anon_chat, name="anon_chat"),
    path(
        "c/<uuid:conv_id>/messages/",
        views.anon_messages,
        name="anon_messages",
    ),
    path("c/<uuid:conv_id>/send/", views.anon_send, name="anon_send"),
    path("c/<uuid:conv_id>/typing/", views.anon_typing, name="anon_typing"),
    path("c/<uuid:conv_id>/read/", views.anon_read, name="anon_read"),
    path("c/<uuid:conv_id>/leave/", views.anon_leave, name="anon_leave"),

    # Legacy leader-id chat link: now requires the institution room code.
    path("chat/<uuid:leader_id>/", views.chat_room, name="chat"),
    path(
        "chat/<uuid:conv_id>/send/",
        views.send_message,
        name="send_message",
    ),

    # Leader / counsellor side
    path("leader/signin/", views.leader_signin, name="signin"),
    path("leader/inbox/", views.leader_inbox, name="leader_inbox"),
    path("leader/profile/", views.leader_profile, name="leader_profile"),
    path("leader/inbox/data/", views.leader_inbox_data, name="leader_inbox_data"),
    path("leader/chat/<uuid:conv_id>/", views.leader_chat, name="leader_chat"),
    path(
        "leader/chat/<uuid:conv_id>/messages/",
        views.leader_messages,
        name="leader_messages",
    ),
    path(
        "leader/chat/<uuid:conv_id>/send/",
        views.leader_send,
        name="leader_send",
    ),
    path(
        "leader/chat/<uuid:conv_id>/typing/",
        views.leader_typing,
        name="leader_typing",
    ),
    path(
        "leader/chat/<uuid:conv_id>/read/",
        views.leader_read,
        name="leader_read",
    ),
    path(
        "leader/chat/<uuid:conv_id>/note/",
        views.leader_note,
        name="leader_note",
    ),
    path(
        "leader/chat/<uuid:conv_id>/resolve/",
        views.leader_resolve,
        name="leader_resolve",
    ),
    path(
        "leader/chat/<uuid:conv_id>/reopen/",
        views.leader_reopen,
        name="leader_reopen",
    ),
    path(
        "leader/chat/<uuid:conv_id>/transfer/",
        views.leader_transfer,
        name="leader_transfer",
    ),
    path(
        "leader/chat/<uuid:conv_id>/report/",
        views.leader_report,
        name="leader_report",
    ),
    path(
        "leader/chat/<uuid:conv_id>/block/",
        views.leader_block,
        name="leader_block",
    ),
    path(
        "leader/chat/<uuid:conv_id>/unblock/",
        views.leader_unblock,
        name="leader_unblock",
    ),
    path("leader/logout/", views.leader_logout, name="logout"),
]
