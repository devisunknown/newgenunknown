"""Shared chat services: identity, rooms, safety, serialisation, broadcasting."""

import hashlib
import re
import secrets
import time
import uuid
from datetime import timedelta
from zlib import crc32

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import strip_tags

from .models import (
    Anonymous,
    BlockedAlias,
    Conversation,
    Institution,
    Leader,
    Message,
    Room,
    RoomCodeAttempt,
)
from .randomizers import random_alias


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_token(token: str) -> bool:
    return bool(token) and 20 <= len(token) <= 200


def get_device_token(request) -> str | None:
    token = request.COOKIES.get(settings.ANON_DEVICE_COOKIE, "")
    return token if _valid_token(token) else None


def ensure_device_token(request) -> str:
    token = get_device_token(request)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    # The view/response is responsible for setting the cookie.
    request._whisper_new_device_token = token
    return token


def get_anonymous_for_request(request, create=False):
    """Resolve the current anonymous person without storing network data.

    Preference order:
    1. a device token that matches an existing Anonymous row;
    2. the session's anon_id (useful when a cookie was just set);
    3. a brand-new Anonymous row, only when ``create`` is true.
    """
    token = get_device_token(request)
    if token:
        anonymous = Anonymous.objects.filter(
            device_token_hash=hash_token(token)
        ).first()
        if anonymous:
            # Only touch the session when it actually needs it: assigning the
            # same value marks it modified, which rewrites the row and pushes
            # its expiry on every single request.
            if request.session.get("anon_id") != str(anonymous.id):
                request.session["anon_id"] = str(anonymous.id)
            return anonymous

    anon_id = request.session.get("anon_id")
    if anon_id:
        anonymous = Anonymous.objects.filter(id=anon_id).first()
        if anonymous:
            # Re-attach a newly issued token to the existing session identity.
            if token and not anonymous.device_token_hash:
                anonymous.device_token_hash = hash_token(token)
                anonymous.save(update_fields=["device_token_hash"])
            return anonymous

    if not create:
        return None

    token = token or ensure_device_token(request)
    for _ in range(8):
        anonymous = Anonymous(
            alias=random_alias(), device_token_hash=hash_token(token)
        )
        try:
            with transaction.atomic():
                anonymous.save()
            request.session["anon_id"] = str(anonymous.id)
            return anonymous
        except IntegrityError:
            # Alias or token collision: try another alias, but never create a
            # second row for the same token.
            existing = Anonymous.objects.filter(
                device_token_hash=hash_token(token)
            ).first()
            if existing:
                request.session["anon_id"] = str(existing.id)
                return existing
    raise RuntimeError("Could not allocate an anonymous identity")


def set_device_cookie(response, request):
    token = getattr(request, "_whisper_new_device_token", None)
    if token:
        response.set_cookie(
            settings.ANON_DEVICE_COOKIE,
            token,
            max_age=settings.ANON_DEVICE_COOKIE_AGE,
            httponly=True,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
        )
    return response


# ---------------------------------------------------------------------------
# Rooms / access
# ---------------------------------------------------------------------------

def room_for_slug(slug: str):
    return (
        Room.objects.select_related("institution")
        .filter(institution__slug=slug)
        .first()
    )


def grant_room_access(request, room: Room):
    request.session["room_id"] = str(room.id)
    request.session["room_access_at"] = timezone.now().isoformat()


def has_room_access(request, room: Room) -> bool:
    if request.session.get("room_id") != str(room.id):
        return False
    granted = request.session.get("room_access_at")
    if not granted:
        return False
    try:
        granted_at = timezone.datetime.fromisoformat(granted)
        if timezone.is_naive(granted_at):
            granted_at = timezone.make_aware(granted_at)
    except (TypeError, ValueError):
        return False
    return timezone.now() - granted_at < timedelta(
        hours=settings.ROOM_ACCESS_HOURS
    )


def room_is_available(room: Room | None) -> bool:
    return bool(room and room.is_enabled)


def get_or_create_conversation(leader: Leader, anonymous: Anonymous):
    institution = leader.institution
    conv, created = Conversation.objects.get_or_create(
        leader=leader,
        anonymous=anonymous,
        defaults={"institution": institution},
    )
    changed = False
    if conv.institution_id is None and institution is not None:
        conv.institution = institution
        changed = True
    if not created and conv.status == Conversation.STATUS_RESOLVED:
        conv.status = Conversation.STATUS_OPEN
        changed = True
    if changed:
        conv.save(update_fields=["institution", "status", "updated_at"])
    return conv, created


def is_blocked(anonymous: Anonymous, institution) -> bool:
    if not anonymous or not institution:
        return False
    return BlockedAlias.objects.filter(
        anonymous=anonymous, institution=institution
    ).exists()


# ---------------------------------------------------------------------------
# Rate limiting / lockout
# ---------------------------------------------------------------------------

def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Simple fixed-window limiter. Returns True when the action is allowed."""
    cache_key = f"rl:{key}"
    try:
        added = cache.add(cache_key, 1, window_seconds)
        if added:
            return True
        current = cache.get(cache_key, 0)
        if current >= limit:
            return False
        try:
            cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, current + 1, window_seconds)
        return True
    except Exception:
        # A cache outage must not take the chat down.
        return True


def code_attempt_key(request) -> str:
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    token = get_device_token(request) or ""
    return hashlib.sha256(f"{session_key}:{token}".encode()).hexdigest()


def code_attempt_state(request):
    """Return (attempt, is_locked, seconds_remaining, throttle_wait)."""
    key = code_attempt_key(request)
    attempt, _ = RoomCodeAttempt.objects.get_or_create(key_hash=key)
    now = timezone.now()
    if attempt.locked_until and attempt.locked_until > now:
        remaining = int((attempt.locked_until - now).total_seconds())
        return attempt, True, remaining, False
    if attempt.last_attempt_at and now - attempt.last_attempt_at < timedelta(
        seconds=1
    ):
        return attempt, False, 0, True
    return attempt, False, 0, False


def record_code_failure(request):
    key = code_attempt_key(request)
    attempt, _ = RoomCodeAttempt.objects.get_or_create(key_hash=key)
    now = timezone.now()
    if attempt.locked_until and attempt.locked_until <= now:
        attempt.failures = 0
        attempt.locked_until = None
    attempt.failures += 1
    attempt.last_attempt_at = now
    if attempt.failures >= settings.ROOM_CODE_MAX_ATTEMPTS:
        attempt.locked_until = now + timedelta(
            minutes=settings.ROOM_CODE_LOCKOUT_MINUTES
        )
    attempt.save(
        update_fields=[
            "failures",
            "last_attempt_at",
            "locked_until",
            "updated_at",
        ]
    )
    return attempt


def reset_code_attempts(request):
    key = code_attempt_key(request)
    RoomCodeAttempt.objects.filter(key_hash=key).update(
        failures=0, locked_until=None, last_attempt_at=timezone.now()
    )


# --- Per-room budget -------------------------------------------------------
# The lockout above is keyed on the session + device cookie, so a script that
# throws its cookies away starts fresh on every request.  This budget is shared
# by everyone entering one room and keeps no identifiers at all -- no address,
# no cookie, no user agent -- so it survives both cookie clearing and a
# distributed guessing run.  A scripted search for a 4-digit code is capped at
# a few thousand guesses a day, and pauses grow from minutes to a day.
#
# The cost is that a determined attacker can pause code entry for a room.  That
# is deliberate: better a busy signal for a while than a guessable room, and a
# leader who is already signed in never needs the code.

_ROOM_CODE_BUDGET = "roomcode:room:{}"


def _budget_key(room) -> str:
    return _ROOM_CODE_BUDGET.format(getattr(room, "id", "") or "")


def room_code_budget(room):
    """Return (allowed, seconds_until_allowed) for the room as a whole."""
    try:
        state = cache.get(_budget_key(room)) or {}
    except Exception:
        # A cache outage must not lock everyone out of their own room.
        return True, 0
    until = state.get("until", 0) or 0
    now = time.time()
    if until > now:
        return False, int(until - now)
    return True, 0


def record_room_code_failure(room):
    """Count a wrong code against the room and pause entry once spent."""
    key = _budget_key(room)
    now = time.time()
    window = int(
        getattr(settings, "ROOM_CODE_ROOM_WINDOW_MINUTES", 15) * 60
    )
    limit = int(getattr(settings, "ROOM_CODE_ROOM_MAX_FAILURES", 20))
    base = int(settings.ROOM_CODE_LOCKOUT_MINUTES * 60)
    max_pause = int(
        getattr(settings, "ROOM_CODE_MAX_LOCKOUT_HOURS", 24) * 3600
    )
    try:
        state = cache.get(key) or {}
        failures = int(state.get("failures", 0))
        strikes = int(state.get("strikes", 0))
        window_end = state.get("window_end", 0) or 0
        until = state.get("until", 0) or 0
        last_pause = state.get("last_pause", 0) or 0

        # A quiet room starts again at zero, and long-ago strikes stop
        # counting so an old attack does not punish today's visitors.
        if window_end <= now:
            failures = 0
            window_end = now + window
        if last_pause and now - last_pause > 6 * 3600:
            strikes = 0

        failures += 1
        if failures >= limit:
            strikes += 1
            until = now + min(base * (2 ** (strikes - 1)), max_pause)
            failures = 0
            window_end = now
            last_pause = now

        state = {
            "failures": failures,
            "window_end": window_end,
            "strikes": strikes,
            "until": until,
            "last_pause": last_pause,
        }
        cache.set(key, state, max(max_pause * 2, 3600))
        return state
    except Exception:
        return {}


def reset_room_code_budget(room):
    """A correct code clears the room's failures."""
    try:
        cache.delete(_budget_key(room))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Content safety
# ---------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAFETY_PATTERNS = [
    (
        "self-harm",
        re.compile(
            r"\b(kill myself|killing myself|suicide|suicidal|end my life|"
            r"want to die|wanna die|better off dead|no reason to live|"
            r"self[- ]?harm|hurt myself|cut myself|cutting myself|overdose)\b",
            re.I,
        ),
    ),
    (
        "abuse",
        re.compile(
            r"\b(abusing me|abused me|hitting me|hits me|beats me|beat me|"
            r"raped me|rape|molested me|molesting me|sexual abuse|"
            r"threatened to kill|threatening to kill|domestic violence)\b",
            re.I,
        ),
    ),
    (
        "emergency",
        re.compile(
            r"\b(in immediate danger|emergency|urgent help|help me now|"
            r"trapped|someone is trying to hurt me)\b",
            re.I,
        ),
    ),
]


def sanitize_message(body: str) -> str:
    """Remove markup/control characters and normalise whitespace.

    The UI always renders with textContent / Django autoescaping.  This is a
    second layer so stored data itself is harmless if exported or rendered by
    a future template.
    """
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    body = _CONTROL_CHARS.sub("", body)
    body = strip_tags(body)
    body = body.strip()
    if len(body) > 4000:
        body = body[:4000].rstrip()
    return body


def detect_safety(body: str) -> str | None:
    for reason, pattern in _SAFETY_PATTERNS:
        if pattern.search(body or ""):
            return reason
    return None


def helplines_payload():
    return {
        "note": settings.EMERGENCY_NOTE,
        "numbers": settings.EMERGENCY_HELPLINES,
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _time_label(value):
    if not value:
        return ""
    return timezone.localtime(value).strftime("%H:%M")


def _initials(name):
    parts = str(name or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _avatar_tone(name):
    return "tone-%d" % (crc32(str(name or "").encode("utf-8")) % 6)


def date_key(value):
    return timezone.localtime(value).date().isoformat()


def message_payload(message: Message, viewer_role: str):
    """Serialise a message for JSON.

    Only the alias and leader display details are exposed.  The anonymous
    database id, device token, IP and user agent are never included.
    """
    sender = message.sender
    is_system = message.sender_type == Message.SENDER_SYSTEM
    is_mine = message.sender_type == viewer_role and not is_system

    if message.sender_type == Message.SENDER_ANON:
        sender_name = message.conversation.alias
        role_label = ""
    elif message.sender_type == Message.SENDER_LEADER:
        sender_name = sender.name if sender else "Support team"
        role_label = sender.role_label if sender else ""
    else:
        sender_name = ""
        role_label = ""

    return {
        "id": str(message.id),
        "body": message.body,
        "sender_type": message.sender_type,
        "sender_name": sender_name,
        "role_label": role_label,
        "is_mine": is_mine,
        "is_system": is_system,
        "is_internal": message.is_internal,
        "is_read": message.is_read,
        "delivered": bool(message.delivered_at),
        "created_at": message.created_at.isoformat(),
        "date": date_key(message.created_at),
        "time_label": _time_label(message.created_at),
        "client_id": message.client_id or "",
    }


def conversation_payload(conversation: Conversation, viewer_role: str):
    return {
        "id": str(conversation.id),
        "alias": conversation.alias,
        "leader_name": conversation.leader.name if conversation.leader else "",
        "leader_role": (
            conversation.leader.role_label if conversation.leader else ""
        ),
        "status": conversation.status,
        "needs_attention": conversation.needs_attention,
        "attention_reason": conversation.attention_reason,
        "last_message_at": (
            conversation.last_message_at.isoformat()
            if conversation.last_message_at
            else ""
        ),
        "last_message_preview": conversation.last_message_preview,
        "viewer_role": viewer_role,
    }


def inbox_item(conversation: Conversation):
    unread = conversation.messages.filter(
        sender_type=Message.SENDER_ANON,
        is_read=False,
        is_internal=False,
    ).count()
    return {
        "id": str(conversation.id),
        "alias": conversation.alias,
        "initials": _initials(conversation.alias),
        "avatar_tone": _avatar_tone(conversation.alias),
        "leader_name": conversation.leader.name,
        "leader_role": conversation.leader.role,
        "leader_role_label": conversation.leader.role_label,
        "status": conversation.status,
        "needs_attention": conversation.needs_attention,
        "attention_reason": conversation.attention_reason,
        "unread": unread,
        "last_message": conversation.last_message_preview,
        "last_message_at": (
            conversation.last_message_at.isoformat()
            if conversation.last_message_at
            else ""
        ),
        "time_label": _time_label(conversation.last_message_at),
    }


# ---------------------------------------------------------------------------
# Read / delivered state
# ---------------------------------------------------------------------------

def mark_delivered(conversation: Conversation, recipient_role: str):
    """Mark messages from the other side as delivered."""
    sender_type = (
        Message.SENDER_ANON
        if recipient_role == Message.SENDER_LEADER
        else Message.SENDER_LEADER
    )
    now = timezone.now()
    qs = conversation.messages.filter(
        sender_type=sender_type, delivered_at__isnull=True, is_internal=False
    )
    ids = list(qs.values_list("id", flat=True))
    if ids:
        qs.update(delivered_at=now)
    return ids


def mark_read(conversation: Conversation, reader_role: str):
    sender_type = (
        Message.SENDER_ANON
        if reader_role == Message.SENDER_LEADER
        else Message.SENDER_LEADER
    )
    now = timezone.now()
    qs = conversation.messages.filter(
        sender_type=sender_type, is_read=False, is_internal=False
    )
    ids = [str(i) for i in qs.values_list("id", flat=True)]
    if ids:
        qs.update(is_read=True, read_at=now, delivered_at=now)
    return ids


# ---------------------------------------------------------------------------
# Broadcasting
# ---------------------------------------------------------------------------

def conversation_group(conversation_id) -> str:
    return f"chat_{conversation_id}"


def leader_group(leader_id) -> str:
    return f"leader_{leader_id}"


def group_send(group: str, event: dict):
    layer = get_channel_layer()
    if not layer:
        return
    try:
        async_to_sync(layer.group_send)(group, event)
    except Exception:
        # Realtime is best-effort; HTTP polling is the fallback.
        pass


def broadcast_message(conversation: Conversation, message: Message):
    group_send(
        conversation_group(conversation.id),
        {
            "type": "chat_message",
            "payload": message_payload(
                message,
                Message.SENDER_ANON,
            ),
        },
    )


def broadcast_event(conversation: Conversation, event_type: str, **payload):
    group_send(
        conversation_group(conversation.id),
        {"type": "conversation_event", "event": event_type, **payload},
    )


def notify_leader_inbox(conversation: Conversation):
    group_send(
        leader_group(conversation.leader_id),
        {"type": "inbox_update", "payload": inbox_item(conversation)},
    )
    maybe_email_leader(conversation)


def maybe_email_leader(conversation: Conversation):
    if not settings.LEADER_EMAIL_NOTIFICATIONS:
        return
    leader = conversation.leader
    if not leader or not leader.email:
        return
    try:
        send_mail(
            subject="New anonymous message in anylink",
            message=(
                f"You have a new anonymous message from {conversation.alias}.\n"
                "Open your inbox to reply. Their identity is hidden."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[leader.email],
            fail_silently=True,
        )
    except Exception:
        pass


def create_system_message(conversation: Conversation, body: str):
    message = Message.objects.create(
        conversation=conversation,
        sender_type=Message.SENDER_SYSTEM,
        body=body,
        is_read=True,
        delivered_at=timezone.now(),
        read_at=timezone.now(),
    )
    conversation.touch(body, message.created_at)
    broadcast_message(conversation, message)
    return message


def make_client_id(value: str | None) -> str:
    value = (value or "").strip()
    if value and len(value) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return uuid.uuid4().hex


def get_or_create_message(
    conversation: Conversation,
    *,
    body: str,
    sender_type: str,
    sender: Leader | None,
    client_id: str,
    is_internal: bool = False,
):
    if client_id:
        existing = Message.objects.filter(
            conversation=conversation, client_id=client_id
        ).first()
        if existing:
            return existing, False
    message = Message.objects.create(
        conversation=conversation,
        sender_type=sender_type,
        sender=sender,
        body=body,
        client_id=client_id,
        is_internal=is_internal,
    )
    # Private notes must not change the inbox preview or ordering.
    if not is_internal:
        conversation.touch(body, message.created_at)
    return message, True


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------
# A short-lived cache flag is the source of truth while a socket is open. It
# is refreshed by the client's heartbeat and expires on its own, so a dropped
# connection can never leave someone "online" forever.
PRESENCE_TTL = 120


def _presence_key(kind: str, ident) -> str:
    return f"presence:{kind}:{ident}"


def mark_present(kind: str, ident) -> None:
    if kind and ident:
        cache.set(_presence_key(kind, ident), True, PRESENCE_TTL)


def clear_presence(kind: str, ident) -> None:
    if kind and ident:
        cache.delete(_presence_key(kind, ident))


def is_present(kind: str, ident) -> bool:
    return bool(ident) and bool(cache.get(_presence_key(kind, ident)))
