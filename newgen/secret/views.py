import json
from functools import wraps
from uuid import UUID

from django.conf import settings
from django.contrib import messages as django_messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AbuseReport,
    Anonymous,
    BlockedAlias,
    Conversation,
    Institution,
    Leader,
    Message,
    Room,
)
from .services import (
    broadcast_event,
    broadcast_message,
    code_attempt_state,
    conversation_group,
    conversation_payload,
    create_system_message,
    detect_safety,
    get_anonymous_for_request,
    get_or_create_conversation,
    get_or_create_message,
    grant_room_access,
    group_send,
    has_room_access,
    helplines_payload,
    inbox_item,
    is_blocked,
    make_client_id,
    mark_delivered,
    mark_read,
    notify_leader_inbox,
    rate_limit,
    record_code_failure,
    record_room_code_failure,
    reset_code_attempts,
    reset_room_code_budget,
    room_code_budget,
    room_for_slug,
    room_is_available,
    is_present,
    sanitize_message,
    set_device_cookie,
    mark_present,
)

QUICK_REPLIES = [
    "Thank you for trusting me with this.",
    "I'm here with you. Take your time.",
    "That sounds really hard. Can you tell me a little more?",
    "You are not alone in this.",
    "Would it help to talk about what happened next?",
    "I'm listening. There is no judgement here.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_data(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST


def _current_leader(request):
    leader_id = request.session.get("leader_id")
    if not leader_id:
        return None
    return (
        Leader.objects.select_related("institution")
        .filter(id=leader_id, is_active=True)
        .first()
    )


def leader_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        leader = _current_leader(request)
        if not leader:
            return redirect("signin")
        request.leader = leader
        return view(request, *args, **kwargs)

    return wrapper


def _is_institution_admin(leader):
    if leader.is_admin:
        return True
    # Safety net for older data: the earliest active leader can bootstrap the
    # room if nobody has been marked admin yet.
    if not leader.institution_id:
        return False
    if Leader.objects.filter(
        institution=leader.institution, is_admin=True, is_active=True
    ).exists():
        return False
    first = (
        Leader.objects.filter(
            institution=leader.institution, is_active=True
        )
        .order_by("created_at")
        .first()
    )
    return bool(first and first.id == leader.id)


def _anon_conversation(request, conv_id):
    anonymous = get_anonymous_for_request(request, create=False)
    if not anonymous:
        raise Http404
    return get_object_or_404(
        Conversation.objects.select_related("leader", "anonymous", "institution"),
        id=conv_id,
        anonymous=anonymous,
    )


def _leader_conversation(leader, conv_id):
    return get_object_or_404(
        Conversation.objects.select_related("leader", "anonymous", "institution"),
        id=conv_id,
        leader=leader,
    )


def _ws_url(request, path):
    scheme = "wss" if request.is_secure() else "ws"
    return f"{scheme}://{request.get_host()}{path}"


def _finish(response, request):
    return set_device_cookie(response, request)


def _message_rate_ok(conversation, anonymous):
    return rate_limit(
        f"msg-conv:{conversation.id}",
        settings.MESSAGE_RATE_LIMIT_PER_MINUTE,
        60,
    ) and rate_limit(
        f"msg-anon:{anonymous.id}",
        settings.MESSAGE_RATE_LIMIT_PER_HOUR,
        3600,
    )


def _typing_cache_key(conversation, role):
    return f"typing:{conversation.id}:{role}"


def _room_for_conversation(conversation):
    if not conversation.institution_id:
        return None
    return Room.objects.filter(institution_id=conversation.institution_id).first()


# ---------------------------------------------------------------------------
# Anonymous entry flow
# ---------------------------------------------------------------------------

def room_entry(request, room_id):
    """One-time code entry for a room, addressed by its UUID."""
    room = get_object_or_404(
        Room.objects.select_related("institution"), id=room_id
    )
    institution = room.institution
    error = ""
    locked_seconds = 0
    wants_json = request.headers.get("x-requested-with") == "fetch"

    if request.method == "POST":
        digits = request.POST.getlist("digit")
        code = (
            "".join((d or "").strip() for d in digits)
            if digits
            else (request.POST.get("code") or "")
        ).strip()
        attempt, locked, remaining, throttle = code_attempt_state(request)
        room_allowed, room_wait = room_code_budget(room)
        if locked or not room_allowed:
            # How long the caller waits is deliberately vague; only the screen
            # countdown uses the exact figure.
            locked_seconds = remaining or room_wait
            error = (
                "Too many attempts. Please wait a few minutes before trying "
                "again."
            )
        elif throttle:
            error = "Please wait a moment and try again."
        elif not code:
            error = "Enter the room code to continue."
        elif room.is_enabled and room.check_code(code):
            reset_code_attempts(request)
            reset_room_code_budget(room)
            grant_room_access(request, room)
            target = reverse("room_directory", args=[room.id])
            if wants_json:
                return _finish(
                    JsonResponse({"ok": True, "redirect": target}), request
                )
            return _finish(redirect(target), request)
        else:
            record_code_failure(request)
            record_room_code_failure(room)
            # Deliberately identical whether the code is wrong or the room is
            # paused; the room's existence is never announced.
            error = "That code didn't work. Please check it and try again."

        if wants_json:
            return _finish(
                JsonResponse(
                    {
                        "ok": False,
                        "error": error,
                        "locked": bool(locked_seconds),
                    },
                    status=429 if (throttle or locked_seconds) else 400,
                ),
                request,
            )

    if request.method == "GET" and has_room_access(request, room):
        return redirect("room_directory", room_id=room.id)

    code_length = room.code_length
    context = {
        "room": room,
        "institution": institution,
        "error": error,
        "locked_seconds": locked_seconds,
        "room_available": room.is_enabled,
        "code_length": code_length,
        "code_slots": range(1, code_length + 1),
    }
    page = render(request, "room_entry.html", context)
    # Say 429 on the plain form path too, so a throttled or locked caller reads
    # as rate limited rather than "wrong code" to anything caching or logging.
    if request.method == "POST" and (throttle or locked_seconds):
        page.status_code = 429
    return _finish(page, request)


def _directory_context(request, room):
    anonymous = get_anonymous_for_request(request, create=False)
    existing = {}
    if anonymous:
        existing = {
            str(c.leader_id): c
            for c in Conversation.objects.filter(
                anonymous=anonymous, institution=room.institution
            ).select_related("leader")
        }

    leaders = list(
        Leader.objects.filter(
            institution=room.institution,
            is_active=True,
            role__in=[Leader.ROLE_LEADER, Leader.ROLE_COUNSELLOR],
        ).order_by("role", "name")
    )
    for person in leaders:
        person.online_now = is_present("leader", person.id)

    return {
        "room": room,
        "institution": room.institution,
        "leaders": leaders,
        "existing": existing,
        "alias": anonymous.alias if anonymous else "",
        "data_url": reverse("room_people_data", args=[room.id]),
        "directory_url": reverse("room_directory", args=[room.id]),
        "nav_active": "directory",
        "nav_directory_url": reverse("room_directory", args=[room.id]),
    }


def room_people(request, room_id):
    room = get_object_or_404(
        Room.objects.select_related("institution"), id=room_id
    )
    if not room.is_enabled or not has_room_access(request, room):
        return redirect("room_entry", room_id=room.id)

    context = _directory_context(request, room)
    return _finish(render(request, "room_people.html", context), request)


@require_GET
def room_people_data(request, room_id):
    """HTML fragment for the lazily loaded leader directory."""
    room = get_object_or_404(
        Room.objects.select_related("institution"), id=room_id
    )
    if not room.is_enabled or not has_room_access(request, room):
        return JsonResponse(
            {"error": "Enter the room code first."}, status=403
        )
    return render(
        request, "partials/people_list.html", _directory_context(request, room)
    )


@require_POST
def start_chat(request, room_id, leader_id):
    room = get_object_or_404(Room, id=room_id)
    if not room.is_enabled or not has_room_access(request, room):
        return redirect("room_entry", room_id=room.id)

    leader = get_object_or_404(
        Leader,
        id=leader_id,
        institution=room.institution,
        is_active=True,
    )
    anonymous = get_anonymous_for_request(request, create=True)
    if is_blocked(anonymous, room.institution):
        return _finish(
            render(
                request,
                "chat_blocked.html",
                {"institution": room.institution, "alias": anonymous.alias},
            ),
            request,
        )
    conversation, _ = get_or_create_conversation(leader, anonymous)
    return _finish(
        redirect("anon_chat", conv_id=conversation.id), request
    )


def anon_chat(request, conv_id):
    conversation = _anon_conversation(request, conv_id)
    room = _room_for_conversation(conversation)
    room_enabled = bool(room and room.is_enabled)
    blocked = is_blocked(conversation.anonymous, conversation.institution)

    if not blocked:
        delivered_ids = mark_delivered(conversation, Message.SENDER_ANON)
        read_ids = mark_read(conversation, Message.SENDER_ANON)
        if delivered_ids:
            broadcast_event(
                conversation,
                "delivered_receipt",
                reader=Message.SENDER_ANON,
                message_ids=[str(i) for i in delivered_ids],
            )
        if read_ids:
            broadcast_event(
                conversation,
                "read_receipt",
                reader=Message.SENDER_ANON,
                message_ids=read_ids,
            )

    qs = conversation.messages.select_related("sender").filter(
        is_internal=False
    )
    total = qs.count()
    messages = list(qs.order_by("-created_at")[:30])
    messages.reverse()

    oldest = messages[0].created_at.isoformat() if messages else ""
    last_at = messages[-1].created_at.isoformat() if messages else ""
    mark_present("anon", conversation.id)
    ws_url = _ws_url(request, f"/ws/chat/{conversation.id}/anon/")
    context = {
        "peer_online": is_present("leader", conversation.leader_id),
        "conversation": conversation,
        "leader": conversation.leader,
        "alias": conversation.alias,
        "chat_messages": messages,
        "has_more": total > len(messages),
        "oldest_created_at": oldest,
        "can_send": room_enabled and not blocked,
        "blocked": blocked,
        "room_enabled": room_enabled,
        "helplines": helplines_payload(),
        "ws_url": ws_url,
        "quick_replies": [],
        "is_leader_view": False,
        "directory_url": (
            reverse("room_directory", args=[room.id])
            if room
            else reverse("directory")
        ),
        "chat_config": {
            "conversationId": str(conversation.id),
            "role": "anon",
            "myRoleLabel": "",
            "wsUrl": ws_url,
            "messagesUrl": reverse("anon_messages", args=[conversation.id]),
            "sendUrl": reverse("anon_send", args=[conversation.id]),
            "typingUrl": reverse("anon_typing", args=[conversation.id]),
            "readUrl": reverse("anon_read", args=[conversation.id]),
            "leaveUrl": reverse("anon_leave", args=[conversation.id]),
            "noteUrl": "",
            "helplines": helplines_payload(),
            "needsAttention": conversation.needs_attention,
            "attentionReason": conversation.attention_reason,
            "canSend": room_enabled and not blocked,
            "isLeaderView": False,
            "hasMore": total > len(messages),
            "oldestCreatedAt": oldest,
            "initialLastAt": last_at,
            "quickReplies": [],
            "status": conversation.status,
            "alias": conversation.alias,
            "leaderName": conversation.leader.name,
            "leaderRole": conversation.leader.role_label,
        },
    }
    return _finish(render(request, "chat.html", context), request)


@require_GET
def anon_messages(request, conv_id):
    conversation = _anon_conversation(request, conv_id)
    qs = conversation.messages.select_related("sender").filter(
        is_internal=False
    )
    after = request.GET.get("after")
    before = request.GET.get("before")
    has_more = False

    if after:
        qs = qs.filter(created_at__gt=after).order_by("created_at")[:100]
        messages = list(qs)
    elif before:
        older = list(
            qs.filter(created_at__lt=before).order_by("-created_at")[:30]
        )
        older.reverse()
        messages = older
        has_more = qs.filter(created_at__lt=before).count() > len(older)
    else:
        messages = list(qs.order_by("-created_at")[:30])
        messages.reverse()
        has_more = qs.count() > len(messages)

    delivered_ids = mark_delivered(conversation, Message.SENDER_ANON)
    if delivered_ids:
        broadcast_event(
            conversation,
            "delivered_receipt",
            reader=Message.SENDER_ANON,
            message_ids=[str(i) for i in delivered_ids],
        )

    room = _room_for_conversation(conversation)
    payload = {
        "messages": [conversation_message_payload(m, "anon") for m in messages],
        "has_more": has_more,
        "oldest_created_at": (
            messages[0].created_at.isoformat() if messages else ""
        ),
        "conversation": conversation_payload(conversation, "anon"),
        "typing": {
            "leader": bool(
                cache_get(_typing_cache_key(conversation, "leader"))
            )
        },
        "blocked": is_blocked(
            conversation.anonymous, conversation.institution
        ),
        "room_enabled": bool(room and room.is_enabled),
    }
    if conversation.needs_attention:
        payload["helplines"] = helplines_payload()
    return JsonResponse(payload)


def conversation_message_payload(message, viewer_role):
    from .services import message_payload

    return message_payload(message, viewer_role)


def cache_get(key):
    from django.core.cache import cache

    return cache.get(key)


@require_POST
def anon_send(request, conv_id):
    conversation = _anon_conversation(request, conv_id)
    data = _json_data(request)
    body = sanitize_message(data.get("body", ""))
    client_id = make_client_id(data.get("client_id"))
    if not body:
        return JsonResponse({"error": "Message is empty."}, status=400)

    room = _room_for_conversation(conversation)
    if not room or not room.is_enabled:
        return JsonResponse(
            {"error": "This room is not accepting messages right now."},
            status=403,
        )
    if is_blocked(conversation.anonymous, conversation.institution):
        return JsonResponse(
            {"error": "This conversation is no longer available."},
            status=403,
        )
    if not _message_rate_ok(conversation, conversation.anonymous):
        return JsonResponse(
            {"error": "You're sending messages too quickly. Please slow down."},
            status=429,
        )

    safety_reason = detect_safety(body)
    message, created = get_or_create_message(
        conversation,
        body=body,
        sender_type=Message.SENDER_ANON,
        sender=None,
        client_id=client_id,
    )
    if created:
        if conversation.status == Conversation.STATUS_RESOLVED:
            conversation.status = Conversation.STATUS_OPEN
            conversation.save(update_fields=["status", "updated_at"])
        if safety_reason:
            conversation.needs_attention = True
            conversation.attention_reason = safety_reason
            conversation.flagged_at = timezone.now()
            conversation.save(
                update_fields=[
                    "needs_attention",
                    "attention_reason",
                    "flagged_at",
                    "updated_at",
                ]
            )
            broadcast_event(
                conversation,
                "attention",
                needs_attention=True,
                reason=safety_reason,
            )
            group_send(
                conversation_group(conversation.id),
                {
                    "type": "conversation_event",
                    "event": "safety_alert",
                    "payload": helplines_payload(),
                },
            )
        broadcast_message(conversation, message)
        notify_leader_inbox(conversation)

    response = JsonResponse(
        {
            "message": conversation_message_payload(message, "anon"),
            "conversation": conversation_payload(conversation, "anon"),
            "safety": (
                helplines_payload()
                if created and safety_reason
                else None
            ),
        }
    )
    return _finish(response, request)


@require_POST
def anon_typing(request, conv_id):
    conversation = _anon_conversation(request, conv_id)
    data = _json_data(request)
    is_typing = bool(data.get("is_typing"))
    from django.core.cache import cache

    if is_typing:
        cache.set(_typing_cache_key(conversation, "anon"), True, 6)
    else:
        cache.delete(_typing_cache_key(conversation, "anon"))
    group_send(
        conversation_group(conversation.id),
        {
            "type": "conversation_event",
            "event": "typing",
            "is_leader": False,
            "is_typing": is_typing,
        },
    )
    return JsonResponse({"ok": True})


@require_POST
def anon_read(request, conv_id):
    conversation = _anon_conversation(request, conv_id)
    ids = mark_read(conversation, Message.SENDER_ANON)
    if ids:
        broadcast_event(
            conversation,
            "read_receipt",
            reader=Message.SENDER_ANON,
            message_ids=ids,
        )
    return JsonResponse({"ok": True, "read": ids})


@require_POST
def anon_leave(request, conv_id):
    conversation = _anon_conversation(request, conv_id)
    anonymous = conversation.anonymous
    conversation.delete()
    response = JsonResponse({"ok": True})
    if not Conversation.objects.filter(anonymous=anonymous).exists():
        anonymous.delete()
        request.session.pop("anon_id", None)
        # Only forget the device token when this identity has no other
        # conversations; otherwise the person would lose access to them.
        response.delete_cookie(settings.ANON_DEVICE_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Leader authentication
# ---------------------------------------------------------------------------

def leader_signin(request):
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        leader = Leader.objects.filter(email__iexact=email, is_active=True).first()
        if leader and leader.check_password(password):
            request.session["leader_id"] = str(leader.id)
            return redirect("leader_inbox")
        return render(
            request,
            "sign_in.html",
            {"error": "Email or password is incorrect."},
        )
    return render(request, "sign_in.html")


def leader_logout(request):
    request.session.flush()
    return redirect("signin")


# ---------------------------------------------------------------------------
# Leader inbox / chat
# ---------------------------------------------------------------------------

def _inbox_queryset(leader, filter_name):
    qs = (
        Conversation.objects.filter(leader=leader)
        .select_related("anonymous", "leader")
        .annotate(
            unread_count=Count(
                "messages",
                filter=Q(
                    messages__sender_type=Message.SENDER_ANON,
                    messages__is_read=False,
                    messages__is_internal=False,
                ),
            )
        )
        .order_by("-last_message_at", "-updated_at")
    )
    if filter_name == "unread":
        qs = qs.filter(unread_count__gt=0)
    elif filter_name == "resolved":
        qs = qs.filter(status=Conversation.STATUS_RESOLVED)
    return qs


@leader_required
def leader_inbox(request):
    leader = request.leader
    mark_present("leader", leader.id)
    filter_name = request.GET.get("filter", "all")
    if filter_name not in {"all", "unread", "resolved"}:
        filter_name = "all"
    conversations = list(_inbox_queryset(leader, filter_name))
    institution = leader.institution
    room = (
        Room.objects.filter(institution=institution).first()
        if institution
        else None
    )
    share_url = (
        request.build_absolute_uri(reverse("room_entry", args=[room.id]))
        if room
        else ""
    )
    unread_total = Conversation.objects.filter(
        leader=leader,
        messages__sender_type=Message.SENDER_ANON,
        messages__is_read=False,
        messages__is_internal=False,
    ).distinct().count()
    recent_conversations = list(
        Conversation.objects.filter(leader=leader)
        .exclude(last_message_at=None)
        .order_by("-last_message_at")[:8]
    )
    context = {
        "leader": leader,
        "conversations": conversations,
        "recent_conversations": recent_conversations,
        "filter": filter_name,
        "unread_total": unread_total,
        "open_total": Conversation.objects.filter(
            leader=leader, status=Conversation.STATUS_OPEN
        ).count(),
        "resolved_total": Conversation.objects.filter(
            leader=leader, status=Conversation.STATUS_RESOLVED
        ).count(),
        "is_institution_admin": _is_institution_admin(leader),
        "room": room,
        "share_url": share_url,
        "ws_url": _ws_url(request, "/ws/leader/inbox/"),
    }
    return render(request, "leader_inbox.html", context)


@leader_required
@require_GET
def leader_inbox_data(request):
    filter_name = request.GET.get("filter", "all")
    if filter_name not in {"all", "unread", "resolved"}:
        filter_name = "all"
    items = [
        inbox_item(c)
        for c in _inbox_queryset(request.leader, filter_name)
    ]
    unread_total = Conversation.objects.filter(
        leader=request.leader,
        messages__sender_type=Message.SENDER_ANON,
        messages__is_read=False,
        messages__is_internal=False,
    ).distinct().count()
    return JsonResponse({"items": items, "unread_total": unread_total})


@leader_required
def leader_profile(request):
    """A leader's own photo and details, plus password change."""
    leader = request.leader
    errors = {}

    if request.method == "POST":
        section = request.POST.get("section", "profile")
        if section == "password":
            current = request.POST.get("current_password") or ""
            new = request.POST.get("new_password") or ""
            confirm = request.POST.get("confirm_password") or ""
            if not leader.check_password(current):
                errors["password"] = "Your current password is incorrect."
            elif new != confirm:
                errors["password"] = "The two new passwords don't match."
            elif not new:
                errors["password"] = "Enter a new password."
            else:
                try:
                    validate_password(new, user=None)
                except ValidationError as exc:
                    errors["password"] = " ".join(exc.messages)
                else:
                    leader.set_password(new)
                    leader.save(update_fields=["password"])
                    django_messages.success(
                        request, "Your password has been updated."
                    )
                    return redirect("leader_profile")
        else:
            name = (request.POST.get("name") or "").strip()
            title = (request.POST.get("title") or "").strip()
            bio = (request.POST.get("bio") or "").strip()
            photo = request.FILES.get("avatar")
            if not name:
                errors["profile"] = "Your name can't be empty."
            elif photo and photo.size > 5 * 1024 * 1024:
                errors["profile"] = "Choose a photo smaller than 5 MB."
            elif photo and not (photo.content_type or "").startswith("image/"):
                errors["profile"] = "That file isn't an image."
            else:
                leader.name = name[:100]
                leader.title = title[:100]
                leader.bio = bio[:1000]
                if request.POST.get("remove_photo"):
                    if leader.avatar:
                        leader.avatar.delete(save=False)
                    leader.avatar = None
                if photo:
                    leader.avatar = photo
                leader.save()
                django_messages.success(request, "Profile updated.")
                return redirect("leader_profile")

    return render(
        request,
        "leader_profile.html",
        {"leader": leader, "errors": errors, "nav_active": "profile"},
    )


@leader_required
def leader_chat(request, conv_id):
    leader = request.leader
    conversation = _leader_conversation(leader, conv_id)
    room = _room_for_conversation(conversation)
    mark_delivered(conversation, Message.SENDER_LEADER)
    read_ids = mark_read(conversation, Message.SENDER_LEADER)
    if read_ids:
        broadcast_event(
            conversation,
            "read_receipt",
            reader=Message.SENDER_LEADER,
            message_ids=read_ids,
        )

    qs = conversation.messages.select_related("sender")
    total = qs.count()
    messages = list(qs.order_by("-created_at")[:40])
    messages.reverse()
    institution = conversation.institution or leader.institution
    transfer_targets = Leader.objects.filter(
        institution=institution, is_active=True
    ).exclude(id=leader.id).order_by("role", "name")
    blocked = is_blocked(conversation.anonymous, conversation.institution)
    oldest = messages[0].created_at.isoformat() if messages else ""
    last_at = messages[-1].created_at.isoformat() if messages else ""
    mark_present("leader", leader.id)
    ws_url = _ws_url(request, f"/ws/chat/{conversation.id}/leader/")
    context = {
        "peer_online": is_present("anon", conversation.id),
        "conversation": conversation,
        "leader": leader,
        "alias": conversation.alias,
        "chat_messages": messages,
        "has_more": total > len(messages),
        "oldest_created_at": oldest,
        "transfer_targets": transfer_targets,
        "quick_replies": QUICK_REPLIES,
        "blocked": blocked,
        "helplines": helplines_payload(),
        "ws_url": ws_url,
        "is_leader_view": True,
        "can_send": not blocked,
        "room_enabled": bool(room and room.is_enabled),
        "directory_url": (
            reverse("room_directory", args=[room.id])
            if room
            else reverse("leader_inbox")
        ),
        "chat_config": {
            "conversationId": str(conversation.id),
            "role": "leader",
            "myRoleLabel": leader.role_label,
            "wsUrl": ws_url,
            "messagesUrl": reverse("leader_messages", args=[conversation.id]),
            "sendUrl": reverse("leader_send", args=[conversation.id]),
            "typingUrl": reverse("leader_typing", args=[conversation.id]),
            "readUrl": reverse("leader_read", args=[conversation.id]),
            "leaveUrl": "",
            "noteUrl": reverse("leader_note", args=[conversation.id]),
            "helplines": helplines_payload(),
            "needsAttention": conversation.needs_attention,
            "attentionReason": conversation.attention_reason,
            "canSend": not blocked,
            "isLeaderView": True,
            "hasMore": total > len(messages),
            "oldestCreatedAt": oldest,
            "initialLastAt": last_at,
            "quickReplies": QUICK_REPLIES,
            "status": conversation.status,
            "alias": conversation.alias,
            "leaderName": leader.name,
            "leaderRole": leader.role_label,
        },
    }
    return render(request, "chat.html", context)


@leader_required
@require_GET
def leader_messages(request, conv_id):
    conversation = _leader_conversation(request.leader, conv_id)
    qs = conversation.messages.select_related("sender")
    after = request.GET.get("after")
    before = request.GET.get("before")
    has_more = False
    if after:
        messages = list(
            qs.filter(created_at__gt=after).order_by("created_at")[:100]
        )
    elif before:
        older = list(
            qs.filter(created_at__lt=before).order_by("-created_at")[:40]
        )
        older.reverse()
        messages = older
        has_more = qs.filter(created_at__lt=before).count() > len(older)
    else:
        messages = list(qs.order_by("-created_at")[:40])
        messages.reverse()
        has_more = qs.count() > len(messages)

    delivered_ids = mark_delivered(conversation, Message.SENDER_LEADER)
    if delivered_ids:
        broadcast_event(
            conversation,
            "delivered_receipt",
            reader=Message.SENDER_LEADER,
            message_ids=[str(i) for i in delivered_ids],
        )
    return JsonResponse(
        {
            "messages": [
                conversation_message_payload(m, "leader") for m in messages
            ],
            "has_more": has_more,
            "oldest_created_at": (
                messages[0].created_at.isoformat() if messages else ""
            ),
            "conversation": conversation_payload(conversation, "leader"),
            "typing": {
                "anon": bool(
                    cache_get(_typing_cache_key(conversation, "anon"))
                )
            },
            "blocked": is_blocked(
                conversation.anonymous, conversation.institution
            ),
        }
    )


@leader_required
@require_POST
def leader_send(request, conv_id):
    leader = request.leader
    conversation = _leader_conversation(leader, conv_id)
    data = _json_data(request)
    body = sanitize_message(data.get("body", ""))
    client_id = make_client_id(data.get("client_id"))
    if not body:
        return JsonResponse({"error": "Message is empty."}, status=400)
    if is_blocked(conversation.anonymous, conversation.institution):
        return JsonResponse(
            {"error": "This alias is blocked. Unblock it to reply."},
            status=403,
        )
    if not rate_limit(f"leader-msg:{leader.id}", 60, 60):
        return JsonResponse(
            {"error": "You're sending messages too quickly."}, status=429
        )

    message, created = get_or_create_message(
        conversation,
        body=body,
        sender_type=Message.SENDER_LEADER,
        sender=leader,
        client_id=client_id,
    )
    if created:
        if conversation.status == Conversation.STATUS_RESOLVED:
            conversation.status = Conversation.STATUS_OPEN
            conversation.save(update_fields=["status", "updated_at"])
        broadcast_message(conversation, message)
    return JsonResponse(
        {
            "message": conversation_message_payload(message, "leader"),
            "conversation": conversation_payload(conversation, "leader"),
        }
    )


@leader_required
@require_POST
def leader_typing(request, conv_id):
    conversation = _leader_conversation(request.leader, conv_id)
    data = _json_data(request)
    is_typing = bool(data.get("is_typing"))
    from django.core.cache import cache

    if is_typing:
        cache.set(_typing_cache_key(conversation, "leader"), True, 6)
    else:
        cache.delete(_typing_cache_key(conversation, "leader"))
    group_send(
        conversation_group(conversation.id),
        {
            "type": "conversation_event",
            "event": "typing",
            "is_leader": True,
            "is_typing": is_typing,
        },
    )
    return JsonResponse({"ok": True})


@leader_required
@require_POST
def leader_read(request, conv_id):
    conversation = _leader_conversation(request.leader, conv_id)
    ids = mark_read(conversation, Message.SENDER_LEADER)
    if ids:
        broadcast_event(
            conversation,
            "read_receipt",
            reader=Message.SENDER_LEADER,
            message_ids=ids,
        )
    return JsonResponse({"ok": True, "read": ids})


@leader_required
@require_POST
def leader_note(request, conv_id):
    conversation = _leader_conversation(request.leader, conv_id)
    data = _json_data(request)
    body = sanitize_message(data.get("body", ""))
    if not body:
        return JsonResponse({"error": "Note is empty."}, status=400)
    message, created = get_or_create_message(
        conversation,
        body=body,
        sender_type=Message.SENDER_LEADER,
        sender=request.leader,
        client_id=make_client_id(data.get("client_id")),
        is_internal=True,
    )
    if created:
        # Reaches the leader's other tabs; the anon consumer drops internal
        # messages before they are sent to the anonymous person.
        broadcast_message(conversation, message)
    return JsonResponse(
        {"message": conversation_message_payload(message, "leader")}
    )


@leader_required
@require_POST
def leader_resolve(request, conv_id):
    conversation = _leader_conversation(request.leader, conv_id)
    if conversation.status != Conversation.STATUS_RESOLVED:
        conversation.status = Conversation.STATUS_RESOLVED
        conversation.save(update_fields=["status", "updated_at"])
        create_system_message(
            conversation, "Conversation marked as resolved."
        )
    return _action_response(request, conversation)


@leader_required
@require_POST
def leader_reopen(request, conv_id):
    conversation = _leader_conversation(request.leader, conv_id)
    if conversation.status != Conversation.STATUS_OPEN:
        conversation.status = Conversation.STATUS_OPEN
        conversation.save(update_fields=["status", "updated_at"])
        create_system_message(conversation, "Conversation reopened.")
    return _action_response(request, conversation)


def _action_response(request, conversation):
    if request.content_type == "application/json":
        return JsonResponse(
            {"ok": True, "conversation": conversation_payload(conversation, "leader")}
        )
    return redirect("leader_chat", conv_id=conversation.id)


@leader_required
@require_POST
def leader_transfer(request, conv_id):
    leader = request.leader
    conversation = _leader_conversation(leader, conv_id)
    institution = conversation.institution or leader.institution
    target_id = request.POST.get("target_id") or _json_data(request).get(
        "target_id"
    )
    target = get_object_or_404(
        Leader,
        id=target_id,
        institution=institution,
        is_active=True,
    )
    if target.id == leader.id:
        django_messages.error(request, "Choose someone else to transfer to.")
        return redirect("leader_chat", conv_id=conversation.id)

    old_leader = conversation.leader
    conversation.leader = target
    conversation.institution = institution
    conversation.transferred_from = old_leader
    conversation.transferred_at = timezone.now()
    conversation.status = Conversation.STATUS_OPEN
    conversation.save(
        update_fields=[
            "leader",
            "institution",
            "transferred_from",
            "transferred_at",
            "status",
            "updated_at",
        ]
    )
    create_system_message(
        conversation,
        f"Conversation transferred to {target.name} ({target.role_label}).",
    )
    notify_leader_inbox(conversation)
    django_messages.success(
        request, f"Conversation transferred to {target.name}."
    )
    return redirect("leader_inbox")


@leader_required
@require_POST
def leader_report(request, conv_id):
    leader = request.leader
    conversation = _leader_conversation(leader, conv_id)
    data = _json_data(request)
    reason = (data.get("reason") or "abusive behaviour").strip()[:120]
    note = sanitize_message(data.get("note", ""))
    institution = conversation.institution or leader.institution
    if not institution:
        django_messages.error(
            request, "This conversation is not linked to an institution."
        )
        return _action_response(request, conversation)
    AbuseReport.objects.create(
        institution=institution,
        conversation=conversation,
        anonymous=conversation.anonymous,
        alias=conversation.alias,
        reported_by=leader,
        reason=reason,
        note=note,
    )
    if data.get("block") in {"1", "true", "on", True}:
        BlockedAlias.objects.get_or_create(
            institution=institution,
            anonymous=conversation.anonymous,
            defaults={"blocked_by": leader, "reason": reason},
        )
        conversation.status = Conversation.STATUS_RESOLVED
        conversation.save(update_fields=["status", "updated_at"])
        create_system_message(
            conversation, "This conversation has been closed by the support team."
        )
    django_messages.success(
        request, "Report saved. The anonymous person's identity stays hidden."
    )
    return _action_response(request, conversation)


@leader_required
@require_POST
def leader_block(request, conv_id):
    leader = request.leader
    conversation = _leader_conversation(leader, conv_id)
    institution = conversation.institution or leader.institution
    if not institution:
        django_messages.error(
            request, "This conversation is not linked to an institution."
        )
        return _action_response(request, conversation)
    BlockedAlias.objects.get_or_create(
        institution=institution,
        anonymous=conversation.anonymous,
        defaults={"blocked_by": leader, "reason": "Blocked by support team"},
    )
    conversation.status = Conversation.STATUS_RESOLVED
    conversation.save(update_fields=["status", "updated_at"])
    create_system_message(
        conversation, "This conversation has been closed by the support team."
    )
    django_messages.success(request, "Alias blocked for this institution.")
    return _action_response(request, conversation)


@leader_required
@require_POST
def leader_unblock(request, conv_id):
    leader = request.leader
    conversation = _leader_conversation(leader, conv_id)
    institution = conversation.institution or leader.institution
    if not institution:
        django_messages.error(
            request, "This conversation is not linked to an institution."
        )
        return _action_response(request, conversation)
    BlockedAlias.objects.filter(
        institution=institution,
        anonymous=conversation.anonymous,
    ).delete()
    conversation.status = Conversation.STATUS_OPEN
    conversation.save(update_fields=["status", "updated_at"])
    create_system_message(conversation, "Conversation reopened.")
    django_messages.success(request, "Alias unblocked.")
    return _action_response(request, conversation)


# ---------------------------------------------------------------------------
# Legacy URLs (kept so existing links/bookmarks do not 404)
# ---------------------------------------------------------------------------

def privacy(request):
    return render(request, "privacy.html")


def legacy_room_entry(request, slug):
    """Old /r/<slug>/ links now point at the room's UUID address."""
    room = room_for_slug(slug)
    if not room:
        raise Http404
    if request.method == "POST":
        return room_entry(request, room.id)
    return redirect("room_entry", room_id=room.id, permanent=True)


def legacy_room_directory(request, slug):
    room = room_for_slug(slug)
    if not room:
        raise Http404
    return redirect("room_directory", room_id=room.id, permanent=True)


@require_POST
def legacy_start_chat(request, slug, leader_id):
    room = room_for_slug(slug)
    if not room:
        raise Http404
    return start_chat(request, room.id, leader_id)


def leader_directory(request):
    # Public introduction at /welcome/. Rooms stay invitation-only, so no
    # institution is ever listed here.
    return render(
        request,
        "contact.html",
        {"nav_active": "how", **_visitor_nav(request)},
    )


def landing(request):
    """Public marketing page. The person's chats stay at /inbox/."""
    anonymous = get_anonymous_for_request(request, create=False)
    has_chats = bool(
        anonymous and Conversation.objects.filter(anonymous=anonymous).exists()
    )
    return render(request, "landing.html", {"has_chats": has_chats})


def _visitor_nav(request):
    """The visitor dock is identical on chats, directory and how-it-works."""
    directory = ""
    room_id = request.session.get("room_id")
    if room_id:
        try:
            room = Room.objects.filter(id=UUID(str(room_id))).first()
        except ValueError:
            room = None
        if room and room.is_enabled and has_room_access(request, room):
            directory = reverse("room_directory", args=[room.id])
    return {"nav_directory_url": directory}


def stranger_inbox(request):
    anonymous = get_anonymous_for_request(request, create=False)
    conversations = (
        Conversation.objects.filter(anonymous=anonymous)
        .select_related("leader")
        .order_by("-last_message_at", "-updated_at")
        if anonymous
        else Conversation.objects.none()
    )
    return render(
        request,
        "stranger_inbox.html",
        {"conversations": conversations, "nav_active": "chats", **_visitor_nav(request)},
    )


def chat_room(request, leader_id):
    leader = get_object_or_404(Leader, id=leader_id, is_active=True)
    room = Room.objects.filter(institution=leader.institution).first()
    if room and not has_room_access(request, room):
        return redirect("room_entry", room_id=room.id)
    anonymous = get_anonymous_for_request(request, create=True)
    conversation, _ = get_or_create_conversation(leader, anonymous)
    return _finish(
        redirect("anon_chat", conv_id=conversation.id), request
    )


@require_POST
def send_message(request, conv_id):
    """Legacy HTTP endpoint retained for older clients."""
    data = request.POST
    body = sanitize_message(data.get("body", ""))
    if not body:
        return JsonResponse({"error": "Empty message"}, status=400)
    conversation = get_object_or_404(Conversation, id=conv_id)
    leader_id = request.session.get("leader_id")
    if leader_id and str(conversation.leader_id) == str(leader_id):
        sender_type = Message.SENDER_LEADER
        sender = conversation.leader
    else:
        anonymous = get_anonymous_for_request(request, create=False)
        if not anonymous or conversation.anonymous_id != anonymous.id:
            return JsonResponse({"error": "Not allowed"}, status=403)
        room = _room_for_conversation(conversation)
        if not room or not room.is_enabled:
            return JsonResponse(
                {"error": "This room is not accepting messages right now."},
                status=403,
            )
        if is_blocked(anonymous, conversation.institution):
            return JsonResponse({"error": "Not allowed"}, status=403)
        if not _message_rate_ok(conversation, anonymous):
            return JsonResponse({"error": "Slow down a little."}, status=429)
        sender_type = Message.SENDER_ANON
        sender = None
    message, created = get_or_create_message(
        conversation,
        body=body,
        sender_type=sender_type,
        sender=sender,
        client_id=make_client_id(data.get("client_id")),
    )
    if created:
        if sender_type == Message.SENDER_ANON and detect_safety(body):
            conversation.needs_attention = True
            conversation.attention_reason = detect_safety(body)
            conversation.flagged_at = timezone.now()
            conversation.save(
                update_fields=[
                    "needs_attention",
                    "attention_reason",
                    "flagged_at",
                    "updated_at",
                ]
            )
        broadcast_message(conversation, message)
        if sender_type == Message.SENDER_ANON:
            notify_leader_inbox(conversation)
    return JsonResponse(
        {
            "id": str(message.id),
            "body": message.body,
            "sender_type": message.sender_type,
            "created_at": message.created_at.isoformat(),
        }
    )
