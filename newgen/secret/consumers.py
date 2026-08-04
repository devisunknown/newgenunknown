import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from .models import Conversation, Message, Leader, Anonymous


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conv_id = self.scope['url_route']['kwargs']['conv_id']
        self.requested_role = self.scope['url_route']['kwargs']['role']  # 'anon' or 'leader'
        self.room_group_name = f'chat_{self.conv_id}'

        session = self.scope.get('session', {})

        self.is_leader = False
        self.leader_id = None
        self.anon_id = None

        # Role is decided by which URL the page connected through, NOT by
        # which keys happen to exist in the session. This stops a leader's
        # session from bleeding into an anon tab (or vice versa) when the
        # same browser session has both leader_id and anon_id set.
        if self.requested_role == 'leader':
            leader_id = session.get('leader_id')
            if not leader_id:
                await self.close()
                return
            self.is_leader = True
            self.leader_id = leader_id
        else:
            anon_id = session.get('anon_id')
            if not anon_id:
                await self.close()
                return
            self.is_leader = False
            self.anon_id = anon_id

        # Validate conversation access
        if not await self.can_access_conversation():
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

        # Notify others that user joined (online status)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_online',
                'is_leader': self.is_leader,
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
                'type': 'user_offline',
                'is_leader': self.is_leader,
            }
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type', 'message')

        if msg_type == 'message':
            await self.handle_chat_message(data)
        elif msg_type == 'typing':
            await self.handle_typing(data)
        elif msg_type == 'read_receipt':
            await self.handle_read_receipt(data)

    async def handle_chat_message(self, data):
        body = data.get('message', '').strip()
        if not body:
            return

        if self.is_leader:
            sender_type = 'leader'
            sender_name = await self.get_leader_name()
        else:
            sender_type = 'anon'
            sender_name = 'You (Anonymous)'

        message = await self.save_message(body, sender_type)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': body,
                'sender_type': sender_type,
                'sender_name': sender_name,
                'message_id': str(message.id),
                'timestamp': message.created_at.strftime('%I:%M %p'),
                'sender_is_leader': self.is_leader,
            }
        )

    async def handle_typing(self, data):
        is_typing = data.get('is_typing', False)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'is_typing': is_typing,
                'is_leader': self.is_leader,
            }
        )

    async def handle_chat_message(self, data):
     body = data.get('message', '').strip()
     if not body:
        return

     if self.is_leader:
        sender_type = 'leader'
        sender_name = await self.get_leader_name()
     else:
        sender_type = 'anon'
        sender_name = 'You (Anonymous)'


    # Send instantly to users
     await self.channel_layer.group_send(
        self.room_group_name,
        {
            'type': 'chat_message',
            'message': body,
            'sender_type': sender_type,
            'sender_name': sender_name,
            'timestamp': timezone.now().strftime('%I:%M %p'),
            'sender_is_leader': self.is_leader,
            'message_id': None,
        }
    )


    # Save after sending
     await self.save_message(body, sender_type)
    # ========== EVENT HANDLERS ==========

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'sender_type': event['sender_type'],
            'sender_name': event['sender_name'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
            'sender_is_leader': event['sender_is_leader'],
            'is_me': (event['sender_is_leader'] == self.is_leader),
        }))

    async def typing_indicator(self, event):
        if event['is_leader'] == self.is_leader:
            return
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'is_typing': event['is_typing'],
            'is_leader': event['is_leader'],
        }))

    async def user_online(self, event):
        await self.send(text_data=json.dumps({
            'type': 'online',
            'is_leader': event['is_leader'],
        }))

    async def user_offline(self, event):
        await self.send(text_data=json.dumps({
            'type': 'offline',
            'is_leader': event['is_leader'],
        }))

    async def read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read',
            'message_id': event['message_id'],
        }))

    # ========== DATABASE HELPERS ==========

    @database_sync_to_async
    def can_access_conversation(self):
        try:
            conv = Conversation.objects.get(id=self.conv_id)
            if self.is_leader:
                return str(conv.leader.id) == self.leader_id
            else:
                return conv.anonymous_id is not None and str(conv.anonymous.id) == self.anon_id
        except ObjectDoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, body, sender_type):
        conv = Conversation.objects.get(id=self.conv_id)
        if not self.is_leader and conv.anonymous_id is not None:
            conv.anonymous.last_seen = timezone.now()
            conv.anonymous.save(update_fields=['last_seen'])

        return Message.objects.create(
            conversation=conv,
            sender_type=sender_type,
            body=body
        )

    @database_sync_to_async
    def get_leader_name(self):
        try:
            leader = Leader.objects.get(id=self.leader_id)
            return leader.name
        except ObjectDoesNotExist:
            return 'Support Leader'

    @database_sync_to_async
    def mark_message_read(self, message_id):
        try:
            msg = Message.objects.get(id=message_id)
            msg.is_read = True
            msg.save(update_fields=['is_read'])
        except ObjectDoesNotExist:
            pass