"""Template helpers for the chat UI: dates, aliases, avatars and icons."""

from datetime import date, datetime, timedelta
from zlib import crc32

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
@register.filter
def date_key(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


@register.filter
def human_day(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    today = timezone.localdate()
    if value == today:
        return "Today"
    if value == today - timedelta(days=1):
        return "Yesterday"
    return value.strftime("%b %d, %Y").replace(" 0", " ")


@register.filter
def clock(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value[11:16]
    return timezone.localtime(value).strftime("%H:%M")


@register.filter
def clock12(value):
    """12-hour timestamp for lists and bubbles, e.g. 11:05 AM."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value[11:16]
    return timezone.localtime(value).strftime("%I:%M %p").lstrip("0")


# ---------------------------------------------------------------------------
# Identity / avatars
# ---------------------------------------------------------------------------
@register.filter
def initials(value):
    parts = str(value or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


@register.filter
def avatar_tone(value):
    return "tone-%d" % (crc32(str(value or "").encode("utf-8")) % 6)


@register.filter
def first_word(value):
    parts = str(value or "").split()
    return parts[0] if parts else ""


@register.filter
def get_item(mapping, key):
    if not mapping:
        return None
    try:
        return mapping.get(str(key)) or mapping.get(key)
    except AttributeError:
        return None


@register.filter
def tick_class(message):
    if message.is_read:
        return "read"
    if message.delivered_at:
        return "delivered"
    return "sent"


# ---------------------------------------------------------------------------
# Icons — a small, dependency-free Lucide-style set (no emoji anywhere).
# ---------------------------------------------------------------------------
_ICONS = {
    "arrow-left": '<path d="M15 18l-6-6 6-6"/>',
    "arrow-right": '<path d="M9 18l6-6-6-6"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
    "settings": '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "more": '<circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/>',
    "send": '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-check": '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
    "alert": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "x": '<path d="M18 6 6 18"/><path d="M6 6l12 12"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "refresh": '<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/><path d="M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "power": '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><path d="M12 2v10"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "shield-check": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "moon": '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
    "message": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    "life-buoy": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><path d="m4.93 4.93 4.24 4.24"/><path d="m14.83 14.83 4.24 4.24"/><path d="m14.83 9.17 4.24-4.24"/><path d="m4.93 19.07 4.24-4.24"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "note": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 5L2 7"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "eye-off": '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    "sparkles": '<path d="m12 3 1.9 5.8L20 10l-5.8 1.9L12 18l-1.9-5.8L4 10l5.8-1.9z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "smile": '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
}


@register.simple_tag
def ghost_mark(size=28, cls=""):
    """The anylink ghost mascot. Eyes punch through to the surface colour."""
    classes = ("ghost " + cls).strip()
    height = round(size * 46 / 48, 1)
    return mark_safe(
        f'<svg class="{classes}" width="{size}" height="{height}" viewBox="0 0 48 46" '
        'fill="none" aria-hidden="true">'
        '<path d="M20.5 7.5C11.6 7.5 4.5 13.8 4.5 21.9c0 5.3 2.8 10 7.2 12.8l-1.5 6.1c-.3 1.2 1 2.1 2 1.4l7.4-4.9c.3 0 .6.1.9.1 8.9 0 16-6.3 16-14.4S29.4 7.5 20.5 7.5Z" fill="currentColor"/>'
        '<ellipse cx="16" cy="21.5" rx="3.5" ry="4.5" fill="var(--bg, #fff)" transform="rotate(-14 16 21.5)"/>'
        '<ellipse cx="25.5" cy="21.5" rx="3.5" ry="4.5" fill="var(--bg, #fff)" transform="rotate(-14 25.5 21.5)"/>'
        '<path d="M32.6 12.6 35.7 6.9" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/>'
        '<path d="M38.2 16.4 43 13" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/>'
        '</svg>'
    )


@register.simple_tag
def icon(name, size=20, cls=""):
    """Render a clean stroke icon. Usage: {% icon "lock" 22 "muted" %}."""
    body = _ICONS.get(name, _ICONS["message"])
    classes = ("icon " + cls).strip()
    return mark_safe(
        f'<svg class="{classes}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )
