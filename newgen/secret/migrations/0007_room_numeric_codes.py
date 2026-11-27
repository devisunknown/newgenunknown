import re
import secrets

import django.core.validators
from django.db import migrations, models

ROOM_CODE_RE = re.compile(r"^(?:\d{4}|\d{6})$")


def regenerate_existing_codes(apps, schema_editor):
    Room = apps.get_model("secret", "Room")
    for room in Room.objects.all():
        if ROOM_CODE_RE.fullmatch(room.code or ""):
            continue
        for _ in range(40):
            candidate = "".join(str(secrets.randbelow(10)) for _ in range(6))
            if not Room.objects.filter(code=candidate).exists():
                room.code = candidate
                room.save(update_fields=["code"])
                break


class Migration(migrations.Migration):

    dependencies = [
        (
            "secret",
            "0006_abusereport_alias_alter_abusereport_anonymous_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            regenerate_existing_codes, migrations.RunPython.noop
        ),
        migrations.AlterField(
            model_name="room",
            name="code",
            field=models.CharField(
                blank=True,
                help_text="4 or 6 digits. Leave blank to generate a new one.",
                max_length=12,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        "^(?:\\d{4}|\\d{6})$",
                        "Enter 4 or 6 digits, for example 4821 or 204815.",
                    )
                ],
            ),
        ),
    ]
