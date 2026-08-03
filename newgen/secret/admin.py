from django.contrib import admin
from .models import Leader, Conversation, Message


admin.site.register(Leader)
admin.site.register(Conversation)
admin.site.register(Message)