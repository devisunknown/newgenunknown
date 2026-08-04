from django.contrib import admin
from django.utils.html import format_html
from .models import Leader, Anonymous, Conversation, Message


@admin.register(Leader)
class LeaderAdmin(admin.ModelAdmin):
    list_display = ('photo_thumb', 'name', 'title', 'email', 'is_online', 'created_at')
    list_display_links = ('name',)
    search_fields = ('name', 'email')
    readonly_fields = ('photo_preview', 'created_at')
    fields = ('photo', 'photo_preview', 'name', 'email', 'password', 'title', 'bio', 'is_online', 'created_at')

    def photo_thumb(self, obj):
        if obj.photo:
            url = obj.photo.build_url(width=40, height=40, crop='fill', gravity='face')
            return format_html('<img src="{}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;" />', url)
        return "—"
    photo_thumb.short_description = "Photo"

    def photo_preview(self, obj):
        if obj.photo:
            url = obj.photo.build_url(width=200, height=200, crop='fill', gravity='face')
            return format_html('<img src="{}" style="width:200px;height:200px;border-radius:12px;object-fit:cover;" />', url)
        return "No photo uploaded yet"
    photo_preview.short_description = "Current photo"

    def save_model(self, request, obj, form, change):
        if 'password' in form.changed_data:
            obj.set_password(form.cleaned_data['password'])
        super().save_model(request, obj, form, change)


@admin.register(Anonymous)
class AnonymousAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'last_seen')
    readonly_fields = ('id', 'created_at', 'last_seen', 'ip_hash', 'user_agent_hash')


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'leader', 'anonymous', 'created_at', 'updated_at')
    list_filter = ('leader',)
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender_type', 'short_body', 'is_read', 'created_at')
    list_filter = ('sender_type', 'is_read')
    readonly_fields = ('id', 'created_at')

    def short_body(self, obj):
        return obj.body[:60]
    short_body.short_description = "Message"