import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .models import Conversation, Message, Leader


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.conv_id = self.scope["url_route"]["kwargs"]["conv_id"]
        self.requested_role = self.scope["url_route"]["kwargs"]["role"]

        self.room_group_name = f"chat_{self.conv_id}"

        session = self.scope.get("session", {})

        self.is_leader = self.requested_role == "leader"

        if self.is_leader:
            self.leader_id = session.get("leader_id")

            if not self.leader_id:
                await self.close()
                return

        else:
            self.anon_id = session.get("anon_id")

            if not self.anon_id:
                await self.close()
                return


        if not await self.can_access_conversation():
            await self.close()
            return


        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()


        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_online",
                "is_leader": self.is_leader
            }
        )


    async def disconnect(self, close_code):

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )


        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_offline",
                "is_leader": self.is_leader
            }
        )



    async def receive(self, text_data):

        try:
            data = json.loads(text_data)

        except json.JSONDecodeError:
            return


        msg_type = data.get("type", "message")


        if msg_type == "message":
            await self.handle_chat_message(data)

        elif msg_type == "typing":
            await self.handle_typing(data)



    async def handle_chat_message(self, data):

        body = data.get("message", "").strip()

        if not body:
            return


        if len(body) > 2000:
            return


        sender_type = (
            "leader"
            if self.is_leader
            else "anon"
        )


        sender_name = (
            await self.get_leader_name()
            if self.is_leader
            else "You (Anonymous)"
        )


        timestamp = timezone.now().strftime("%I:%M %p")


        # SEND FIRST - instant UI update
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",

                "message": body,

                "sender_type": sender_type,

                "sender_name": sender_name,

                "timestamp": timestamp,

                "message_id": None,

                "sender_is_leader": self.is_leader,
            }
        )


        # SAVE AFTER BROADCAST
        await self.save_message(
            body,
            sender_type
        )



    async def handle_typing(self, data):

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "typing_indicator",

                "is_typing": data.get(
                    "is_typing",
                    False
                ),

                "is_leader": self.is_leader,
            }
        )



    async def chat_message(self, event):

       await self.send(text_data=json.dumps({
       "type": "message",
       "message": event["message"],
       "sender_type": event["sender_type"],
       "sender_name": event["sender_name"],
       "timestamp": event["timestamp"],
       "message_id": event["message_id"],
       "sender_is_leader": event["sender_is_leader"],
       "is_me": (
           event["sender_is_leader"] == self.is_leader
    ),
}))


    async def typing_indicator(self,event):

        if event["is_leader"] == self.is_leader:
            return


        await self.send(
            text_data=json.dumps(
                {
                    "type":"typing",
                    "is_typing":
                    event["is_typing"]
                }
            )
        )



    async def user_online(self,event):

        await self.send(
            text_data=json.dumps(
                {
                    "type":"online",
                    "is_leader":
                    event["is_leader"]
                }
            )
        )



    async def user_offline(self,event):

        await self.send(
            text_data=json.dumps(
                {
                    "type":"offline",
                    "is_leader":
                    event["is_leader"]
                }
            )
        )



    @database_sync_to_async
    def can_access_conversation(self):

        try:

            conv = Conversation.objects.select_related(
                "leader",
                "anonymous"
            ).get(
                id=self.conv_id
            )


            if self.is_leader:

                return (
                    str(conv.leader.id)
                    ==
                    str(self.leader_id)
                )


            return (
                str(conv.anonymous.id)
                ==
                str(self.anon_id)
            )


        except ObjectDoesNotExist:
            return False



    @database_sync_to_async
    def save_message(self,body,sender_type):

        conv = Conversation.objects.get(
            id=self.conv_id
        )


        return Message.objects.create(
            conversation=conv,

            sender_type=sender_type,

            body=body
        )



    @database_sync_to_async
    def get_leader_name(self):

        try:

            return Leader.objects.only(
                "name"
            ).get(
                id=self.leader_id
            ).name


        except ObjectDoesNotExist:

            return "Support Leader"