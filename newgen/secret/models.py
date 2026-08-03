from django.db import models
import uuid
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


class Leader(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    title = models.CharField(max_length=100, blank=True, default="Community Leader")
    bio = models.TextField(blank=True, default="Here to listen and support you.")
    is_online = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.name


class Anonymous(models.Model):
    """
    Model representing an anonymous user in the system.
    No personally identifiable information is stored.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    # Optional fields for basic abuse prevention (hashed for privacy)
    ip_hash = models.CharField(max_length=64, blank=True, null=True,
                              help_text="SHA256 hash of IP address for basic abuse prevention")
    user_agent_hash = models.CharField(max_length=64, blank=True, null=True,
                                      help_text="SHA256 hash of User-Agent string")

    def __str__(self):
        return f"Anonymous {str(self.id)[:8]}"

    class Meta:
        ordering = ['-last_seen']


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    leader = models.ForeignKey(Leader, on_delete=models.CASCADE, related_name='conversations')
    anonymous = models.ForeignKey(Anonymous, on_delete=models.CASCADE, related_name='conversations', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ['leader', 'anonymous']  # Prevent duplicate conversations between same leader and anonymous user

    def __str__(self):
        anon_id = str(self.anonymous.id)[:8] if self.anonymous else "unknown"
        return f"Conv with {self.leader.name} (anon: {anon_id})"


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender_type = models.CharField(max_length=10, choices=[('leader', 'Leader'), ('anon', 'Anonymous')])
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender_type}: {self.body[:30]}"