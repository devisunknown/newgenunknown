import re
import secrets
import uuid

from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from .randomizers import random_alias, random_room_code

ROOM_CODE_PATTERN = r"^(?:\d{4}|\d{6})$"
room_code_validator = RegexValidator(
    ROOM_CODE_PATTERN,
    "Enter 4 or 6 digits, for example 4821 or 204815.",
)


class Institution(models.Model):
    """A school, church, NGO or other organisation with its own chat room."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Room(models.Model):
    """The single private room belonging to an institution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.OneToOneField(
        Institution, on_delete=models.CASCADE, related_name="room"
    )
    code = models.CharField(
        max_length=12,
        unique=True,
        blank=True,
        validators=[room_code_validator],
        help_text="4 or 6 digits. Leave blank to generate a new one.",
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["institution__name"]

    def __str__(self):
        return f"{self.institution.name} room"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._new_unique_code()
        super().save(*args, **kwargs)

    @classmethod
    def _new_unique_code(cls):
        for _ in range(30):
            code = random_room_code()
            if not cls.objects.filter(code=code).exists():
                return code
        # Extremely unlikely; widen the code rather than fail.
        return random_room_code(8)

    def clean(self):
        super().clean()
        if self.code and not re.fullmatch(ROOM_CODE_PATTERN, self.code):
            raise ValidationError(
                {"code": "Use 4 or 6 digits, for example 4821 or 204815."}
            )

    def regenerate_code(self, length: int = 6):
        for _ in range(30):
            candidate = random_room_code(length)
            if not Room.objects.filter(code=candidate).exists():
                self.code = candidate
                self.save(update_fields=["code", "updated_at"])
                return self.code
        raise RuntimeError("Could not allocate a unique room code")

    @property
    def code_length(self) -> int:
        return len(self.code) if self.code else 6

    def check_code(self, raw_code: str) -> bool:
        if not raw_code:
            return False
        cleaned = re.sub(r"\s+", "", str(raw_code))
        return secrets.compare_digest(self.code, cleaned)


class Leader(models.Model):
    ROLE_LEADER = "leader"
    ROLE_COUNSELLOR = "counsellor"
    ROLE_CHOICES = [
        (ROLE_LEADER, "Leader"),
        (ROLE_COUNSELLOR, "Counsellor"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        related_name="leaders",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    title = models.CharField(max_length=100, blank=True, default="Community Leader")
    bio = models.TextField(blank=True, default="Here to listen and support you.")
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_LEADER
    )
    is_admin = models.BooleanField(
        default=False,
        help_text="Can manage the institution room, code and members.",
    )
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    # Stamped into the session at sign-in.  A password change rotates it, which
    # ends every session opened with the old password, on every device.
    session_epoch = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    avatar = models.ImageField(
        upload_to="leaders/",
        blank=True,
        null=True,
        help_text="Profile photo shown in the directory and chats.",
    )

    class Meta:
        ordering = ["name"]

    @property
    def avatar_url(self):
        """The photo's URL, or "" when the row points at a file that is gone.

        Uploads live on local disk, and hosts that rebuild the app (Render, most
        PaaS) wipe them: the row keeps the old name, so a plain .url would send
        the browser after a 404 and the person would show a broken image.  The
        templates fall back to their initials instead.
        """
        if not self.avatar:
            return ""
        try:
            if not self.avatar.storage.exists(self.avatar.name):
                return ""
            return self.avatar.url
        except (OSError, ValueError):
            return ""

    HASH_PREFIXES = ("argon2$", "pbkdf2_", "bcrypt", "scrypt")

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        if not self.password:
            return False
        if self.password.startswith(self.HASH_PREFIXES):
            matches = check_password(raw_password, self.password)
        else:
            # Rows saved before hashing existed. Verify, then upgrade below.
            matches = secrets.compare_digest(self.password, raw_password)
        if matches and not self.password.startswith("argon2$"):
            self.set_password(raw_password)
            self.save(update_fields=["password"])
        return matches

    @property
    def role_label(self):
        return self.get_role_display()

    def __str__(self):
        return self.name


class Anonymous(models.Model):
    """An anonymous person.

    The only durable identifiers are a friendly alias and a hash of a random
    device token.  No IP address, user agent or contact details are stored.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alias = models.CharField(max_length=64, unique=True)
    device_token_hash = models.CharField(
        max_length=64, blank=True, null=True, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen"]
        verbose_name_plural = "Anonymous people"

    def __str__(self):
        return self.alias

    def save(self, *args, **kwargs):
        if not self.alias:
            self.alias = random_alias()
        super().save(*args, **kwargs)


class Conversation(models.Model):
    STATUS_OPEN = "open"
    STATUS_RESOLVED = "resolved"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_RESOLVED, "Resolved"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
    )
    leader = models.ForeignKey(
        Leader, on_delete=models.CASCADE, related_name="conversations"
    )
    anonymous = models.ForeignKey(
        Anonymous,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN
    )
    needs_attention = models.BooleanField(default=False)
    attention_reason = models.CharField(max_length=255, blank=True, default="")
    flagged_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=160, blank=True, default="")
    transferred_from = models.ForeignKey(
        Leader,
        on_delete=models.SET_NULL,
        related_name="transferred_conversations",
        null=True,
        blank=True,
    )
    transferred_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-updated_at"]
        unique_together = [["leader", "anonymous"]]
        indexes = [
            models.Index(fields=["institution", "last_message_at"]),
            models.Index(fields=["leader", "status", "last_message_at"]),
            models.Index(fields=["anonymous", "last_message_at"]),
        ]

    def __str__(self):
        alias = self.anonymous.alias if self.anonymous else "unknown"
        return f"{alias} ↔ {self.leader.name}"

    @property
    def alias(self):
        return self.anonymous.alias if self.anonymous else "Anonymous"

    def touch(self, preview: str, when=None):
        self.last_message_at = when or timezone.now()
        self.last_message_preview = (preview or "")[:160]
        self.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])


class Message(models.Model):
    SENDER_ANON = "anon"
    SENDER_LEADER = "leader"
    SENDER_SYSTEM = "system"
    SENDER_CHOICES = [
        (SENDER_ANON, "Anonymous"),
        (SENDER_LEADER, "Leader"),
        (SENDER_SYSTEM, "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        Leader,
        on_delete=models.SET_NULL,
        related_name="sent_messages",
        null=True,
        blank=True,
    )
    sender_type = models.CharField(max_length=10, choices=SENDER_CHOICES)
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Private note for leaders. Never shown to the anonymous person.",
    )
    is_read = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    client_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["conversation", "is_internal", "created_at"]),
            models.Index(fields=["conversation", "is_read"]),
        ]

    def __str__(self):
        return f"{self.sender_type}: {self.body[:30]}"


class BlockedAlias(models.Model):
    """An alias blocked inside one institution, without revealing identity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="blocked_aliases"
    )
    anonymous = models.ForeignKey(
        Anonymous, on_delete=models.CASCADE, related_name="blocks"
    )
    blocked_by = models.ForeignKey(
        Leader, on_delete=models.SET_NULL, null=True, blank=True
    )
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["institution", "anonymous"]]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Blocked {self.anonymous.alias}"


class AbuseReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="abuse_reports"
    )
    # Reports outlive the conversation and the anonymous identity so the
    # safety team keeps a record even if the person deletes their chat.
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )
    anonymous = models.ForeignKey(
        Anonymous,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )
    alias = models.CharField(max_length=64, blank=True, default="")
    reported_by = models.ForeignKey(
        Leader, on_delete=models.SET_NULL, null=True, blank=True
    )
    reason = models.CharField(max_length=120, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Report: {self.alias or 'anonymous'}"


class RoomCodeAttempt(models.Model):
    """Persistent lockout state for room-code entry.

    Keyed by a hash of the session + device token.  It deliberately contains
    no IP address or user agent.
    """

    key_hash = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"attempt {self.key_hash[:8]}… ({self.failures})"
