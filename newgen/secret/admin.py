from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    AbuseReport,
    Anonymous,
    BlockedAlias,
    BoardComment,
    BoardPost,
    Conversation,
    Institution,
    Leader,
    Message,
    Room,
    RoomCodeAttempt,
)


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "room_code", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    def room_code(self, obj):
        room = Room.objects.filter(institution=obj).first()
        return room.code if room else "—"

    room_code.short_description = "Room code"


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        "institution",
        "code",
        "digits",
        "is_enabled",
        "chatroom_link",
        "updated_at",
    )
    list_filter = ("is_enabled", "institution")
    search_fields = ("institution__name", "code")
    readonly_fields = ("chatroom_link", "created_at", "updated_at")
    fields = (
        "institution",
        "code",
        "is_enabled",
        "chatroom_link",
        "created_at",
        "updated_at",
    )
    actions = ("generate_six_digit_code", "generate_four_digit_code")

    def digits(self, obj):
        return obj.code_length

    digits.short_description = "Digits"

    def chatroom_link(self, obj):
        if not obj.pk:
            return "Save the room first."
        path = reverse("room_entry", args=[obj.pk])
        return format_html(
            '<a href="{0}" target="_blank" rel="noopener">{0}</a>', path
        )

    chatroom_link.short_description = "Chatroom link"

    @admin.action(description="Generate a new 6-digit code")
    def generate_six_digit_code(self, request, queryset):
        for room in queryset:
            room.regenerate_code(6)
        self.message_user(
            request, f"New 6-digit codes generated for {queryset.count()} room(s)."
        )

    @admin.action(description="Generate a new 4-digit code")
    def generate_four_digit_code(self, request, queryset):
        for room in queryset:
            room.regenerate_code(4)
        self.message_user(
            request, f"New 4-digit codes generated for {queryset.count()} room(s)."
        )

    def save_model(self, request, obj, form, change):
        if not obj.code:
            obj.code = Room._new_unique_code()
        super().save_model(request, obj, form, change)


@admin.register(Leader)
class LeaderAdmin(admin.ModelAdmin):
    list_display = (
        "avatar_thumb",
        "name",
        "title",
        "role",
        "institution",
        "is_admin",
        "is_active",
        "created_at",
    )
    list_filter = ("institution", "role", "is_admin", "is_active")
    list_display_links = ("name",)
    list_editable = ("institution", "role", "is_active")
    search_fields = ("name", "email")
    readonly_fields = ("avatar_preview", "created_at")
    fields = (
        "avatar",
        "avatar_preview",
        "institution",
        "name",
        "email",
        "password",
        "title",
        "bio",
        "role",
        "is_admin",
        "is_active",
        "is_online",
        "created_at",
    )

    def avatar_thumb(self, obj):
        if obj.avatar_url:
            return format_html(
                '<img src="{}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;" />',
                obj.avatar_url,
            )
        return "—"

    avatar_thumb.short_description = "Photo"

    def avatar_preview(self, obj):
        if obj.avatar_url:
            return format_html(
                '<img src="{}" style="width:200px;height:200px;border-radius:12px;object-fit:cover;" />',
                obj.avatar_url,
            )
        return "No photo uploaded yet"

    avatar_preview.short_description = "Current photo"

    def save_model(self, request, obj, form, change):
        if "password" in form.changed_data:
            obj.set_password(form.cleaned_data["password"])
        super().save_model(request, obj, form, change)


@admin.register(Anonymous)
class AnonymousAdmin(admin.ModelAdmin):
    list_display = ("alias", "created_at", "last_seen")
    search_fields = ("alias",)
    readonly_fields = ("id", "alias", "device_token_hash", "created_at", "last_seen")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "alias",
        "leader",
        "institution",
        "status",
        "needs_attention",
        "last_message_at",
    )
    list_filter = ("status", "needs_attention", "institution", "leader")
    search_fields = ("anonymous__alias", "leader__name")
    readonly_fields = ("id", "created_at", "updated_at")
    list_select_related = ("anonymous", "leader", "institution")

    def alias(self, obj):
        return obj.anonymous.alias if obj.anonymous else "—"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "conversation",
        "sender_type",
        "short_body",
        "is_internal",
        "is_read",
        "created_at",
    )
    list_filter = ("sender_type", "is_internal", "is_read")
    search_fields = ("body", "conversation__anonymous__alias")
    readonly_fields = ("id", "created_at", "delivered_at", "read_at")
    list_select_related = ("conversation", "sender")

    def short_body(self, obj):
        return obj.body[:60]

    short_body.short_description = "Message"


@admin.register(BlockedAlias)
class BlockedAliasAdmin(admin.ModelAdmin):
    list_display = ("anonymous", "institution", "blocked_by", "created_at")
    list_filter = ("institution",)
    search_fields = ("anonymous__alias",)


@admin.register(AbuseReport)
class AbuseReportAdmin(admin.ModelAdmin):
    list_display = (
        "alias",
        "institution",
        "reason",
        "reported_by",
        "created_at",
        "resolved",
    )
    list_filter = ("institution", "resolved")
    search_fields = ("alias", "reason")


@admin.register(BoardPost)
class BoardPostAdmin(admin.ModelAdmin):
    list_display = ("alias", "title", "created_at", "bumped_at", "is_hidden")
    list_filter = ("is_hidden",)
    search_fields = ("alias", "title", "body")
    readonly_fields = ("alias", "created_at", "bumped_at")


@admin.register(BoardComment)
class BoardCommentAdmin(admin.ModelAdmin):
    list_display = ("alias", "post", "created_at", "is_hidden")
    list_filter = ("is_hidden",)
    search_fields = ("alias", "body")


@admin.register(RoomCodeAttempt)
class RoomCodeAttemptAdmin(admin.ModelAdmin):
    list_display = ("key_hash", "failures", "locked_until", "updated_at")
    readonly_fields = ("key_hash", "failures", "last_attempt_at", "locked_until")
