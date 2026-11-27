import secrets
import uuid

import django.db.models.deletion
from django.db import migrations, models


ADJECTIVES = [
    "Quiet", "Gentle", "Brave", "Calm", "Kind", "Bright", "Soft", "Steady",
    "Warm", "Clear", "Humble", "Honest", "Silent", "Golden", "Silver", "Blue",
    "Green", "Amber", "Swift", "Mellow", "Noble", "Peaceful", "Hopeful",
    "Curious", "Thoughtful", "Radiant", "Daring", "Patient", "Fearless",
    "Tender", "Wandering", "Sunny", "Starry", "Misty", "Coastal", "Highland",
    "Forest", "River", "Desert", "Island", "Northern", "Southern", "Eastern",
    "Western", "Morning", "Evening", "Midnight", "Dawn", "Twilight", "Open",
]
ANIMALS = [
    "Lion", "Dove", "Eagle", "Owl", "Panther", "Tiger", "Falcon", "Heron",
    "Otter", "Fox", "Wolf", "Deer", "Antelope", "Gazelle", "Dolphin",
    "Whale", "Turtle", "Butterfly", "Firefly", "Sparrow", "Robin", "Swallow",
    "Kite", "Crane", "Pelican", "Ibis", "Cobra", "Python", "Gecko",
    "Chameleon", "Meerkat", "Badger", "Hedgehog", "Squirrel", "Rabbit",
    "Leopard", "Cheetah", "Buffalo", "Elephant", "Giraffe", "Zebra",
    "Hippo", "Rhino", "Camel", "Donkey", "Goat", "Sheep", "Pigeon",
    "Kingfisher", "Woodpecker", "Hummingbird", "Peacock", "Parrot",
]
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _alias(existing):
    for _ in range(100):
        alias = f"{secrets.choice(ADJECTIVES)} {secrets.choice(ANIMALS)}"
        if alias not in existing:
            return alias
    return f"{secrets.choice(ADJECTIVES)} {secrets.choice(ANIMALS)} {secrets.randbelow(900) + 100}"


def _code(existing):
    for _ in range(100):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if code not in existing:
            return code
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def backfill(apps, schema_editor):
    Leader = apps.get_model("secret", "Leader")
    Institution = apps.get_model("secret", "Institution")
    Room = apps.get_model("secret", "Room")
    Anonymous = apps.get_model("secret", "Anonymous")
    Conversation = apps.get_model("secret", "Conversation")
    Message = apps.get_model("secret", "Message")

    institution = None
    if Leader.objects.exists() or Conversation.objects.exists():
        institution, _ = Institution.objects.get_or_create(
            slug="newgen", defaults={"name": "NewGen"}
        )
        Leader.objects.filter(institution__isnull=True).update(
            institution=institution
        )
        if not Leader.objects.filter(
            institution=institution, is_admin=True
        ).exists():
            first = (
                Leader.objects.filter(institution=institution)
                .order_by("created_at")
                .first()
            )
            if first:
                first.is_admin = True
                first.save(update_fields=["is_admin"])

        existing_codes = set(Room.objects.values_list("code", flat=True))
        Room.objects.get_or_create(
            institution=institution,
            defaults={"code": _code(existing_codes), "is_enabled": True},
        )

        for conv in Conversation.objects.all():
            if conv.institution_id is None:
                conv.institution_id = (
                    conv.leader.institution_id or institution.id
                )
                conv.save(update_fields=["institution"])
            # Existing leader messages get their author attached so the UI can
            # show the correct name and role badge.
            Message.objects.filter(
                conversation=conv,
                sender_type="leader",
                sender__isnull=True,
            ).update(sender_id=conv.leader_id)
            last = (
                Message.objects.filter(conversation=conv)
                .order_by("-created_at")
                .first()
            )
            if last:
                conv.last_message_at = last.created_at
                conv.last_message_preview = last.body[:160]
                conv.save(
                    update_fields=[
                        "last_message_at",
                        "last_message_preview",
                    ]
                )
            Message.objects.filter(
                conversation=conv, is_read=True
            ).update(
                delivered_at=models.F("created_at"),
                read_at=models.F("created_at"),
            )

    existing_aliases = set(
        Anonymous.objects.exclude(alias="").values_list("alias", flat=True)
    )
    for anon in Anonymous.objects.filter(alias=""):
        alias = _alias(existing_aliases)
        existing_aliases.add(alias)
        anon.alias = alias
        anon.save(update_fields=["alias"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("secret", "0004_leader_photo_message_secret_mess_convers_c83f2d_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="Institution",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Room",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("code", models.CharField(max_length=12, unique=True)),
                ("is_enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "institution",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="room",
                        to="secret.institution",
                    ),
                ),
            ],
            options={"ordering": ["institution__name"]},
        ),
        migrations.CreateModel(
            name="RoomCodeAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key_hash", models.CharField(max_length=64, unique=True)),
                ("failures", models.PositiveIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="BlockedAlias",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "anonymous",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocks",
                        to="secret.anonymous",
                    ),
                ),
                (
                    "blocked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="secret.leader",
                    ),
                ),
                (
                    "institution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocked_aliases",
                        to="secret.institution",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "unique_together": {("institution", "anonymous")},
            },
        ),
        migrations.CreateModel(
            name="AbuseReport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("reason", models.CharField(blank=True, default="", max_length=120)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved", models.BooleanField(default=False)),
                (
                    "anonymous",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports",
                        to="secret.anonymous",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports",
                        to="secret.conversation",
                    ),
                ),
                (
                    "institution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="abuse_reports",
                        to="secret.institution",
                    ),
                ),
                (
                    "reported_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="secret.leader",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddField(
            model_name="leader",
            name="institution",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="leaders",
                to="secret.institution",
            ),
        ),
        migrations.AddField(
            model_name="leader",
            name="role",
            field=models.CharField(
                choices=[("leader", "Leader"), ("counsellor", "Counsellor")],
                default="leader",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="leader",
            name="is_admin",
            field=models.BooleanField(
                default=False,
                help_text="Can manage the institution room, code and members.",
            ),
        ),
        migrations.AddField(
            model_name="leader",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="anonymous",
            name="alias",
            field=models.CharField(blank=True, default="", max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="anonymous",
            name="device_token_hash",
            field=models.CharField(
                blank=True, db_index=True, max_length=64, null=True
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="institution",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="conversations",
                to="secret.institution",
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="status",
            field=models.CharField(
                choices=[("open", "Open"), ("resolved", "Resolved")],
                default="open",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="needs_attention",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="conversation",
            name="attention_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="conversation",
            name="flagged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="conversation",
            name="last_message_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="conversation",
            name="last_message_preview",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="conversation",
            name="transferred_from",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="transferred_conversations",
                to="secret.leader",
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="transferred_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="sender",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sent_messages",
                to="secret.leader",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="is_internal",
            field=models.BooleanField(
                default=False,
                help_text="Private note for leaders. Never shown to the anonymous person.",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="client_id",
            field=models.CharField(
                blank=True, db_index=True, max_length=64, null=True
            ),
        ),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["institution", "last_message_at"],
                name="secret_conv_institu_94e4f8_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["leader", "status", "last_message_at"],
                name="secret_conv_leader__08ead6_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["anonymous", "last_message_at"],
                name="secret_conv_anonymo_97ae75_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["conversation", "is_internal", "created_at"],
                name="secret_mess_convers_b059ce_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["conversation", "is_read"],
                name="secret_mess_convers_f57c1c_idx",
            ),
        ),
        migrations.AlterField(
            model_name="message",
            name="sender_type",
            field=models.CharField(
                choices=[
                    ("anon", "Anonymous"),
                    ("leader", "Leader"),
                    ("system", "System"),
                ],
                max_length=10,
            ),
        ),
        migrations.RunPython(backfill, noop),
        migrations.AlterField(
            model_name="anonymous",
            name="alias",
            field=models.CharField(max_length=64, unique=True),
        ),
        migrations.RemoveField(
            model_name="anonymous",
            name="ip_hash",
        ),
        migrations.RemoveField(
            model_name="anonymous",
            name="user_agent_hash",
        ),
        migrations.AlterModelOptions(
            name="anonymous",
            options={
                "ordering": ["-last_seen"],
                "verbose_name_plural": "Anonymous people",
            },
        ),
        migrations.AlterModelOptions(
            name="conversation",
            options={
                "ordering": ["-last_message_at", "-updated_at"],
                "unique_together": {("leader", "anonymous")},
            },
        ),
        migrations.AlterModelOptions(
            name="leader",
            options={"ordering": ["name"]},
        ),
        migrations.AlterModelOptions(
            name="message",
            options={"ordering": ["created_at"]},
        ),
    ]
