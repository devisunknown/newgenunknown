import json

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache
from django.utils import timezone

from .models import (
    BlockedAlias,
    Conversation,
    Leader,
    Message,
    Room,
)
from .services import (
    clear_presence,
    detect_safety,
    helplines_payload,
    inbox_item,
    make_client_id,
    mark_present,
    mark_delivered,
    mark_read,
    message_payload,
    rate_limit,
    sanitize_message,
)


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conv_id = self.scope["url_route"]["kwargs"]["conv_id"]
        self.role = self.scope["url_route"]["kwargs"]["role"]
        self.is_leader = self.role == "leader"
        self.group_name = f"chat_{self.conv_id}"
        session = self.scope.get("session")
        if not session:
            await self.close()
            return

        # Reading a database-backed session is a synchronous operation, so it
        # must happen in a worker thread inside the consumer.
        session_values = await database_sync_to_async(
            lambda: {
                "leader_id": session.get("leader_id"),
                "anon_id": session.get("anon_id"),
            }
        )()
        self.leader_id = session_values["leader_id"] if self.is_leader else None
        self.anon_id = session_values["anon_id"] if not self.is_leader else None
        if self.is_leader and not self.leader_id:
            await self.close()
            return
        if not self.is_leader and not self.anon_id:
            await self.close()
            return

        conversation = await self.get_conversation()
        if not conversation:
            await self.close()
            return
        if not await self.can_access(conversation):
            await self.close()
            return

        self.conversation = conversation
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        self.accepted = True
        await self.mark_presence(True)

        # A socket opening means the recipient is present: mark messages as
        # delivered so the sender sees a second tick.
        ids = await self.mark_delivered_db()
        if ids:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "conversation_event",
                    "event": "delivered_receipt",
                    "reader": self.role,
                    "message_ids": ids,
                },
            )

    async def disconnect(self, close_code):
        if getattr(self, "accepted", False):
            await self.mark_presence(False)
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except (ValueError, TypeError):
            return
        msg_type = data.get("type", "message")
        if msg_type == "message":
            await self.handle_message(data)
        elif msg_type == "typing":
            await self.handle_typing(data)
        elif msg_type == "read":
            await self.handle_read()
        elif msg_type == "ping":
            await self.mark_presence(True, broadcast=False)
            await self.send(text_data=json.dumps({"type": "pong"}))

    # -- inbound ---------------------------------------------------------

    async def handle_message(self, data):
        body = sanitize_message(data.get("message") or data.get("body") or "")
        if not body:
            await self.send(
                text_data=json.dumps(
                    {"type": "error", "error": "Message is empty."}
                )
            )
            return
        if len(body) > 4000:
            await self.send(
                text_data=json.dumps(
                    {"type": "error", "error": "Message is too long."}
                )
            )
            return

        allowed, reason = await self.can_send()
        if not allowed:
            await self.send(
                text_data=json.dumps({"type": "error", "error": reason})
            )
            return

        if self.is_leader:
            if not await sync_to_async(rate_limit)(
                f"leader-ws:{self.leader_id}", 60, 60
            ):
                await self.send(
                    text_data=json.dumps(
                        {"type": "error", "error": "Slow down a little."}
                    )
                )
                return
        else:
            if not await sync_to_async(rate_limit)(
                f"msg-conv:{self.conv_id}", 20, 60
            ) or not await sync_to_async(rate_limit)(
                f"msg-anon:{self.anon_id}", 120, 3600
            ):
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "error",
                            "error": "You're sending messages too quickly.",
                        }
                    )
                )
                return

        client_id = make_client_id(data.get("client_id"))
        message, payload, safety = await self.save_message(body, client_id)
        if message is None:
            await self.send(
                text_data=json.dumps(
                    {"type": "error", "error": "Could not send that message."}
                )
            )
            return

        if safety:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "conversation_event",
                    "event": "attention",
                    "needs_attention": True,
                    "reason": safety,
                },
            )
            if not self.is_leader:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "conversation_event",
                        "event": "safety_alert",
                        "payload": helplines_payload(),
                    },
                )

        await self.channel_layer.group_send(
            self.group_name,
            {"type": "chat_message", "payload": payload},
        )

        if not self.is_leader:
            inbox_payload = await self.build_inbox_item()
            if inbox_payload:
                await self.channel_layer.group_send(
                    f"leader_{self.conversation['leader_id']}",
                    {"type": "inbox_update", "payload": inbox_payload},
                )

        # Direct acknowledgement gives the optimistic UI a reliable server id.
        await self.send(
            text_data=json.dumps(
                {
                    "type": "message_ack",
                    "client_id": client_id,
                    "message": payload,
                }
            )
        )

    async def handle_typing(self, data):
        is_typing = bool(data.get("is_typing"))
        key = f"typing:{self.conv_id}:{self.role}"
        if is_typing:
            await sync_to_async(cache.set)(key, True, 6)
        else:
            await sync_to_async(cache.delete)(key)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "conversation_event",
                "event": "typing",
                "is_leader": self.is_leader,
                "is_typing": is_typing,
            },
        )

    async def handle_read(self):
        ids = await self.mark_read_db()
        if ids:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "conversation_event",
                    "event": "read_receipt",
                    "reader": self.role,
                    "message_ids": ids,
                },
            )

    async def mark_presence(self, online, broadcast=True):
        kind = "leader" if self.is_leader else "anon"
        ident = self.leader_id if self.is_leader else self.conv_id
        if online:
            await sync_to_async(mark_present)(kind, ident)
        else:
            await sync_to_async(clear_presence)(kind, ident)
        if broadcast and getattr(self, "group_name", None):
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "conversation_event",
                    "event": "presence",
                    "who": self.role,
                    "online": online,
                },
            )

    # -- outbound --------------------------------------------------------

    async def chat_message(self, event):
        payload = event.get("payload") or {}
        if self.role == "anon" and payload.get("is_internal"):
            return
        payload = dict(payload)
        payload["is_mine"] = payload.get("sender_type") == self.role
        await self.send(
            text_data=json.dumps({"type": "message", "message": payload})
        )

    async def conversation_event(self, event):
        name = event.get("event")
        if name in {"read_receipt", "delivered_receipt"}:
            if event.get("reader") == self.role:
                return
        if name == "typing" and event.get("is_leader") == self.is_leader:
            return
        if name == "safety_alert" and self.is_leader:
            return
        await self.send(
            text_data=json.dumps(
                {
                    "type": "event",
                    "event": name,
                    "payload": {
                        k: v
                        for k, v in event.items()
                        if k not in {"type", "event"}
                    },
                }
            )
        )

    # -- database helpers ------------------------------------------------

    @database_sync_to_async
    def get_conversation(self):
        conv = (
            Conversation.objects.select_related(
                "leader", "anonymous", "institution"
            )
            .filter(id=self.conv_id)
            .first()
        )
        if not conv:
            return None
        return {
            "id": str(conv.id),
            "leader_id": str(conv.leader_id),
            "anonymous_id": str(conv.anonymous_id) if conv.anonymous_id else None,
            "institution_id": str(conv.institution_id) if conv.institution_id else None,
            "status": conv.status,
            "needs_attention": conv.needs_attention,
        }

    async def can_access(self, conversation):
        if self.is_leader:
            if conversation["leader_id"] != str(self.leader_id):
                return False
            return await self.leader_is_active()
        return conversation["anonymous_id"] == str(self.anon_id)

    @database_sync_to_async
    def leader_is_active(self):
        return Leader.objects.filter(
            id=self.leader_id, is_active=True
        ).exists()

    @database_sync_to_async
    def can_send(self):
        conv = Conversation.objects.select_related(
            "institution", "anonymous"
        ).filter(id=self.conv_id).first()
        if not conv:
            return False, "Conversation not found."
        if conv.status == Conversation.STATUS_RESOLVED and not self.is_leader:
            # An anonymous person can revive a resolved thread by writing.
            conv.status = Conversation.STATUS_OPEN
            conv.save(update_fields=["status", "updated_at"])
        if conv.institution_id and BlockedAlias.objects.filter(
            institution_id=conv.institution_id,
            anonymous_id=conv.anonymous_id,
        ).exists():
            return (
                False,
                "This alias is blocked."
                if self.is_leader
                else "This conversation is no longer available.",
            )
        if not self.is_leader:
            room = (
                Room.objects.filter(institution_id=conv.institution_id).first()
                if conv.institution_id
                else None
            )
            if not room or not room.is_enabled:
                return False, "This room is not accepting messages right now."
        return True, ""

    @database_sync_to_async
    def save_message(self, body, client_id):
        conv = Conversation.objects.select_related(
            "institution", "anonymous", "leader"
        ).filter(id=self.conv_id).first()
        if not conv:
            return None, None, None
        existing = Message.objects.filter(
            conversation=conv, client_id=client_id
        ).first()
        if existing:
            return (
                existing,
                message_payload(existing, "anon"),
                None,
            )
        sender = conv.leader if self.is_leader else None
        message = Message.objects.create(
            conversation=conv,
            sender_type=(
                Message.SENDER_LEADER if self.is_leader else Message.SENDER_ANON
            ),
            sender=sender,
            body=body,
            client_id=client_id,
        )
        safety = None
        if not self.is_leader:
            safety = detect_safety(body)
            if safety:
                conv.needs_attention = True
                conv.attention_reason = safety
                conv.flagged_at = timezone.now()
                conv.save(
                    update_fields=[
                        "needs_attention",
                        "attention_reason",
                        "flagged_at",
                        "updated_at",
                    ]
                )
        conv.touch(body, message.created_at)
        return message, message_payload(message, "anon"), safety

    @database_sync_to_async
    def build_inbox_item(self):
        conv = Conversation.objects.select_related(
            "leader", "anonymous"
        ).filter(id=self.conv_id).first()
        if not conv:
            return None
        return inbox_item(conv)

    @database_sync_to_async
    def mark_delivered_db(self):
        conv = Conversation.objects.filter(id=self.conv_id).first()
        if not conv:
            return []
        return [str(i) for i in mark_delivered(conv, self.role)]

    @database_sync_to_async
    def mark_read_db(self):
        conv = Conversation.objects.filter(id=self.conv_id).first()
        if not conv:
            return []
        return mark_read(conv, self.role)


class LeaderInboxConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        session = self.scope.get("session")
        if not session:
            await self.close()
            return
        leader_id = await database_sync_to_async(session.get)("leader_id")
        if not leader_id:
            await self.close()
            return
        self.leader_id = leader_id
        active = await self.leader_is_active()
        if not active:
            await self.close()
            return
        self.group_name = f"leader_{leader_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        self.accepted = True
        await database_sync_to_async(mark_present)("leader", leader_id)

    async def disconnect(self, close_code):
        if getattr(self, "accepted", False):
            await database_sync_to_async(clear_presence)(
                "leader", self.leader_id
            )
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except (ValueError, TypeError):
            return
        if data.get("type") == "ping":
            await database_sync_to_async(mark_present)(
                "leader", self.leader_id
            )
            await self.send(text_data=json.dumps({"type": "pong"}))

    async def inbox_update(self, event):
        await self.send(
            text_data=json.dumps(
                {"type": "inbox_update", "payload": event.get("payload")}
            )
        )

    @database_sync_to_async
    def leader_is_active(self):
        return Leader.objects.filter(
            id=self.leader_id, is_active=True
        ).exists()
