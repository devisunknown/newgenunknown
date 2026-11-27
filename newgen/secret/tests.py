import json

from django.conf import settings
from django.urls import reverse
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from newgen.asgi import application

from secret.models import (
    Anonymous,
    BoardComment,
    BoardPost,
    Conversation,
    Institution,
    Leader,
    Message,
    Room,
)


class ChatTestBase(TestCase):
    """Base class providing shared fixtures for chat tests."""
    def setUp(self):
        super().setUp()
        self.institution = Institution.objects.create(
            name="Test Institution", slug="test-inst"
        )
        self.room = Room.objects.create(
            institution=self.institution, code="4821"
        )
        self.leader = Leader.objects.create(
            institution=self.institution,
            name="Test Leader",
            email="test@example.com",
            role=Leader.ROLE_LEADER,
        )
        self.leader.set_password("password123")
        self.leader.save()
        self.anon = Anonymous.objects.create()
        self.conversation = Conversation.objects.create(
            leader=self.leader,
            anonymous=self.anon,
            institution=self.institution,
        )

    def enter_room(self, code="4821"):
        return self.client.post(
            reverse("room_entry", args=[self.room.id]),
            {"code": code},
        )

    def sign_in(self, leader=None):
        leader = leader or self.leader
        response = self.client.post(
            reverse("signin"),
            {"email": leader.email, "password": "password123"},
        )
        return response

    def anon_send(self, conversation, body):
        return self.client.post(
            reverse("anon_send", args=[conversation.id]),
            data=json.dumps({"body": body}),
            content_type="application/json",
        )


class AccountSecurityTests(ChatTestBase):
    def test_passwords_are_argon2_hashed_and_plaintext_rows_are_upgraded(self):
        leader = self.leader
        leader.set_password("a-long-enough-secret")
        self.assertTrue(leader.password.startswith("argon2$"))
        self.assertNotIn("a-long-enough-secret", leader.password)
        self.assertTrue(leader.check_password("a-long-enough-secret"))
        self.assertFalse(leader.check_password("not-the-password"))

        leader.password = "legacy-plain-text"
        leader.save(update_fields=["password"])
        self.assertTrue(leader.check_password("legacy-plain-text"))
        leader.refresh_from_db()
        self.assertTrue(leader.password.startswith("argon2$"))
        self.assertTrue(leader.check_password("legacy-plain-text"))

    def test_leader_can_update_profile_and_password(self):
        from secret.services import get_anonymous_for_request
        self.sign_in(self.leader)
        page = self.client.get(reverse("leader_profile"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Change password")

        response = self.client.post(
            reverse("leader_profile"),
            {"section": "profile", "name": "Renamed Leader", "title": "Peer supporter", "bio": "Here to listen."},
        )
        self.assertEqual(response.status_code, 302)
        self.leader.refresh_from_db()
        self.assertEqual(self.leader.name, "Renamed Leader")
        self.assertEqual(self.leader.title, "Peer supporter")

        self.leader.set_password("old-password-123")
        self.leader.save(update_fields=["password"])
        response = self.client.post(
            reverse("leader_profile"),
            {
                "section": "password",
                "current_password": "old-password-123",
                "new_password": "brand-new-password-9",
                "confirm_password": "brand-new-password-9",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("signin"))
        self.leader.refresh_from_db()
        self.assertTrue(self.leader.check_password("brand-new-password-9"))
        self.assertTrue(self.leader.password.startswith("argon2$"))
        # The old session is gone: the inbox asks them to sign in again.
        self.assertEqual(
            self.client.get(reverse("leader_inbox")).status_code, 302
        )

    def test_profile_requires_a_leader_session(self):
        response = self.client.get(reverse("leader_profile"))
        self.assertEqual(response.status_code, 302)

    def test_directory_shows_presence_for_present_leaders(self):
        from .services import is_present, mark_present

        self.enter_room()
        mark_present("leader", self.leader.id)
        self.assertTrue(is_present("leader", self.leader.id))
        data = self.client.get(
            reverse("room_people_data", args=[self.room.id])
        )
        self.assertEqual(data.status_code, 200)
        self.assertContains(data, "Online now")


class WebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.institution = Institution.objects.create(
            name="Socket School", slug="socket-school"
        )
        self.room = Room.objects.create(
            institution=self.institution, code="3141"
        )
        self.leader = Leader.objects.create(
            institution=self.institution,
            name="Socket Leader",
            email="socket@example.com",
            role=Leader.ROLE_LEADER,
        )
        self.leader.set_password("password123")
        self.leader.save()

    def test_websocket_sends_a_message(self):
        client = Client()
        session = client.session
        session["room_id"] = str(self.room.id)
        session["room_access_at"] = timezone.now().isoformat()
        session.save()
        self.anon = Anonymous.objects.create()
        session = client.session
        session["anon_id"] = str(self.anon.id)
        session.save()
        self.conversation = Conversation.objects.create(
            leader=self.leader,
            anonymous=self.anon,
            institution=self.institution,
        )
        session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value

        async_to_sync(self._websocket_roundtrip)(self.conversation.id, session_cookie)

        self.assertTrue(
            Message.objects.filter(
                conversation=self.conversation,
                body="Hello over the socket",
                client_id="ws-client-1",
            ).exists()
        )

    async def _websocket_roundtrip(self, conversation_id, session_cookie):
        # Keep the whole conversation in one event loop: multiple
        # async_to_sync calls would cancel the consumer between frames.
        communicator = WebsocketCommunicator(
            application,
            f"/ws/chat/{conversation_id}/anon/",
            headers=[
                (
                    b"cookie",
                    f"{settings.SESSION_COOKIE_NAME}={session_cookie}".encode(),
                )
            ],
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.send_json_to(
            {
                "type": "message",
                "message": "Hello over the socket",
                "client_id": "ws-client-1",
            }
        )

        received = await communicator.receive_json_from(timeout=3)
        if received.get("type") != "message_ack":
            received = await communicator.receive_json_from(timeout=3)
        self.assertEqual(received["type"], "message_ack")
        await communicator.disconnect()


class LeaderWorkflowTests(ChatTestBase):
    def test_leader_cannot_read_another_leaders_conversation(self):
        other = Leader.objects.create(
            institution=self.institution,
            name="Other Counsellor",
            email="other@example.com",
            role=Leader.ROLE_COUNSELLOR,
        )
        other.set_password("password123")
        other.save()
        theirs = Conversation.objects.create(
            leader=other,
            anonymous=Anonymous.objects.create(),
            institution=self.institution,
        )
        self.sign_in(self.leader)
        response = self.client.get(reverse("leader_chat", args=[theirs.id]))
        self.assertEqual(response.status_code, 404)

    def test_leader_profile_can_change_password(self):
        self.sign_in(self.leader)
        self.leader.set_password("old-password-123")
        self.leader.save(update_fields=["password"])
        response = self.client.post(
            reverse("leader_profile"),
            {
                "section": "password",
                "current_password": "old-password-123",
                "new_password": "brand-new-password-9",
                "confirm_password": "brand-new-password-9",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.leader.refresh_from_db()
        self.assertTrue(self.leader.check_password("brand-new-password-9"))

    def test_password_change_ends_sessions_on_every_device(self):
        other_device = Client()
        other_device.post(
            reverse("signin"),
            {"email": self.leader.email, "password": "password123"},
        )
        self.assertEqual(
            other_device.get(reverse("leader_inbox")).status_code, 200
        )

        self.sign_in(self.leader)
        self.leader.set_password("old-password-123")
        self.leader.save(update_fields=["password"])
        response = self.client.post(
            reverse("leader_profile"),
            {
                "section": "password",
                "current_password": "old-password-123",
                "new_password": "brand-new-password-9",
                "confirm_password": "brand-new-password-9",
            },
        )
        self.assertEqual(response.url, reverse("signin"))

        # This device and the other one both have to sign in again.
        self.assertEqual(
            self.client.get(reverse("leader_inbox")).status_code, 302
        )
        other_device.get(reverse("leader_inbox"))
        self.assertEqual(
            other_device.get(reverse("leader_inbox")).status_code, 302
        )

        # The old password is dead, the new one signs in.
        retry = other_device.post(
            reverse("signin"),
            {"email": self.leader.email, "password": "password123"},
        )
        self.assertEqual(retry.status_code, 200)
        signed_in = other_device.post(
            reverse("signin"),
            {"email": self.leader.email, "password": "brand-new-password-9"},
        )
        self.assertEqual(signed_in.status_code, 302)
        self.assertEqual(
            other_device.get(reverse("leader_inbox")).status_code, 200
        )

    def test_leader_profile_updates_name_and_title(self):
        self.sign_in(self.leader)
        response = self.client.post(
            reverse("leader_profile"),
            {
                "section": "profile",
                "name": "Renamed Leader",
                "title": "Peer supporter",
                "bio": "Here to listen.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.leader.refresh_from_db()
        self.assertEqual(self.leader.name, "Renamed Leader")
        self.assertEqual(self.leader.title, "Peer supporter")


class LegacyTests(ChatTestBase):
    def test_legacy_slug_link_redirects_to_the_room_uuid(self):
        response = self.client.get(f"/r/{self.institution.slug}/")
        self.assertEqual(response.status_code, 301)
        self.assertIn(f"/chatroom/{self.room.id}/", response.url)

    def test_legacy_slug_directory_redirects(self):
        response = self.client.get(f"/r/{self.institution.slug}/directory/")
        self.assertEqual(response.status_code, 301)
        self.assertIn(f"/chatroom/{self.room.id}/", response.url)


class RoomEntryTests(ChatTestBase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()

    def test_room_entry_light_body(self):
        page = self.client.get(reverse("room_entry", args=[self.room.id]))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertNotIn('class="theme-dark', html)
        self.assertIn('<body class="app-page">', html)
        self.assertIn("data-theme-toggle", html)

    def test_room_codes_are_4_or_6_digits(self):
        # A fresh client per attempt: one client hammering the form trips the
        # one-second throttle, which is covered by the rate-limit tests.
        wrong_codes = ["0000", "9999", "000000", "999999", "12345"]
        for code in wrong_codes:
            if code == self.room.code:
                continue
            response = Client().post(
                reverse("room_entry", args=[self.room.id]), {"code": code}
            )
            self.assertEqual(response.status_code, 200, code)

        response = Client().post(
            reverse("room_entry", args=[self.room.id]), {"code": self.room.code}
        )
        self.assertEqual(response.status_code, 302)

    def test_room_entry_disabled_but_keeps_history(self):
        conversation = self.conversation
        session = self.client.session
        session["anon_id"] = str(self.anon.id)
        session.save()
        self.anon_send(conversation, "Before disable")
        self.room.is_enabled = False
        self.room.save(update_fields=["is_enabled", "updated_at"])

        response = self.anon_send(conversation, "After disable")
        self.assertEqual(response.status_code, 403)

        chat = self.client.get(reverse("anon_chat", args=[conversation.id]))
        self.assertEqual(chat.status_code, 200)
        self.assertContains(chat, "Before disable")

    def test_visitor_navigation_is_the_same_on_every_screen(self):
        self.enter_room()
        screens = (
            reverse("directory"),
            reverse("welcome"),
            reverse("room_people", args=[self.room.id]),
        )
        for url in screens:
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            self.assertContains(page, ">Chats<")
            self.assertContains(page, ">Directory<")
            self.assertContains(page, ">How it works<")
            self.assertContains(page, "nav-item--active", count=1)

    def test_brute_force_without_cookies_is_rate_limited(self):
        """A script that drops its cookies must still be stopped."""
        from django.core.cache import cache

        cache.clear()
        correct = self.room.code
        wrong = "0000" if correct != "0000" else "1111"

        for _ in range(settings.ROOM_CODE_ROOM_MAX_FAILURES):
            # A fresh client per attempt: no session, no device cookie.
            response = Client().post(
                reverse("room_entry", args=[self.room.id]), {"code": wrong}
            )
            self.assertEqual(response.status_code, 200)

        blocked = Client().post(
            reverse("room_entry", args=[self.room.id]), {"code": correct}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, "Too many attempts", status_code=429)

        # Another room keeps working; the pause belongs to this room only.
        other_institution = Institution.objects.create(
            name="Other", slug="other-inst"
        )
        other = Room.objects.create(
            institution=other_institution, code="9999"
        )
        allowed = Client().post(
            reverse("room_entry", args=[other.id]), {"code": "9999"}
        )
        self.assertEqual(allowed.status_code, 302)

    def test_room_pause_escalates_and_a_correct_code_clears_it(self):
        from django.core.cache import cache

        from secret.services import (
            _budget_key,
            record_room_code_failure,
            reset_room_code_budget,
            room_code_budget,
        )

        limit = settings.ROOM_CODE_ROOM_MAX_FAILURES
        for _ in range(limit):
            record_room_code_failure(self.room)
        allowed, first = room_code_budget(self.room)
        self.assertFalse(allowed)
        self.assertGreaterEqual(first, 1)

        # Let the pause run out, then spend the budget again: the next pause is
        # longer, because the strikes are remembered.
        state = cache.get(_budget_key(self.room))
        state["until"] = 0
        cache.set(_budget_key(self.room), state, 3600)
        for _ in range(limit):
            record_room_code_failure(self.room)
        allowed, second = room_code_budget(self.room)
        self.assertFalse(allowed)
        self.assertGreater(second, first)

        # While paused the right code is refused too, and nothing is reset.
        blocked = Client().post(
            reverse("room_entry", args=[self.room.id]), {"code": self.room.code}
        )
        self.assertEqual(blocked.status_code, 429)

        # Once the pause ends, a correct code clears the room's budget.
        reset_room_code_budget(self.room)
        allowed, _ = room_code_budget(self.room)
        self.assertTrue(allowed)
        response = Client().post(
            reverse("room_entry", args=[self.room.id]), {"code": self.room.code}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(cache.get(_budget_key(self.room)))


class SessionStorageTests(ChatTestBase):
    """How leader and anonymous sessions are actually kept."""

    def test_leader_signin_rotates_a_planted_session_key(self):
        from django.contrib.sessions.models import Session
        from django.utils import timezone

        planted = "a" * 32
        Session.objects.create(
            session_key=planted,
            session_data="",
            expire_date=timezone.now() + timezone.timedelta(days=1),
        )
        client = Client()
        client.cookies[settings.SESSION_COOKIE_NAME] = planted
        response = client.post(
            reverse("signin"),
            {"email": self.leader.email, "password": "password123"},
        )
        self.assertEqual(response.status_code, 302)

        used = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertNotEqual(used, planted, "sign-in must not adopt a planted key")
        self.assertEqual(
            Session.objects.get(session_key=used).get_decoded()["leader_id"],
            str(self.leader.id),
        )
        # The old key is now an empty session, not an authenticated one.
        remaining = Session.objects.filter(
            session_key=planted, expire_date__gt=timezone.now()
        ).first()
        if remaining:
            self.assertNotIn("leader_id", remaining.get_decoded())

    def test_wrong_password_creates_no_leader_session(self):
        from django.contrib.sessions.models import Session

        client = Client()
        response = client.post(
            reverse("signin"),
            {"email": self.leader.email, "password": "not-the-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Session.objects.filter(
                session_data__contains="leader_id"
            ).exists()
        )

    def test_logout_removes_the_leader_session_row(self):
        from django.contrib.sessions.models import Session

        self.sign_in(self.leader)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertTrue(Session.objects.filter(session_key=key).exists())

        self.client.get(reverse("logout"))
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(
            self.client.get(reverse("leader_inbox")).status_code, 302
        )

    def test_deactivated_leader_session_stops_working(self):
        self.sign_in(self.leader)
        self.assertEqual(self.client.get(reverse("leader_inbox")).status_code, 200)

        self.leader.is_active = False
        self.leader.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("leader_inbox")).status_code, 302)

        self.leader.is_active = True
        self.leader.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("leader_inbox")).status_code, 200)

    def test_anonymous_session_holds_identity_and_room_grant(self):
        from django.contrib.sessions.models import Session

        self.enter_room()
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        data = Session.objects.get(session_key=key).get_decoded()
        self.assertEqual(data["room_id"], str(self.room.id))
        self.assertIn("room_access_at", data)
        self.assertNotIn("anon_id", data)

        response = self.client.post(
            reverse("start_chat", args=[self.room.id, self.leader.id])
        )
        self.assertEqual(response.status_code, 302)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        data = Session.objects.get(session_key=key).get_decoded()
        self.assertIn("anon_id", data)
        self.assertTrue(
            Anonymous.objects.filter(id=data["anon_id"]).exists()
        )
        self.assertTrue(response.cookies.get(settings.ANON_DEVICE_COOKIE))

        # Plain browsing must not rewrite the session row.
        before = Session.objects.get(session_key=key)
        before_expiry = before.expire_date
        self.client.get(reverse("directory"))
        after = Session.objects.get(session_key=key)
        self.assertEqual(after.expire_date, before_expiry)

    def test_anonymous_identity_survives_a_lost_session_cookie(self):
        from django.contrib.sessions.models import Session

        self.enter_room()
        started = self.client.post(
            reverse("start_chat", args=[self.room.id, self.leader.id])
        )
        conv_id = started["Location"].strip("/").split("/")[-1]
        device = self.client.cookies[settings.ANON_DEVICE_COOKIE].value
        Session.objects.all().delete()

        resumed = Client()
        resumed.cookies[settings.ANON_DEVICE_COOKIE] = device
        self.assertEqual(
            resumed.get(reverse("anon_chat", args=[conv_id])).status_code, 200
        )

        stranger = Client()
        self.assertEqual(
            stranger.get(reverse("anon_chat", args=[conv_id])).status_code, 404
        )

    def test_leader_session_does_not_open_anonymous_screens(self):
        self.sign_in(self.leader)
        self.assertEqual(
            self.client.get(reverse("anon_chat", args=[self.conversation.id])).status_code,
            404,
        )


class InstallableAppTests(ChatTestBase):
    """The add-to-home-screen pieces: manifest, service worker, prompt."""

    static_dir = settings.BASE_DIR / "secret" / "static" / "secret"

    def test_manifest_is_served_as_a_web_app_manifest(self):
        response = self.client.get(reverse("manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")

        data = json.loads(response.content)
        self.assertEqual(data["name"], "anylink")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertIn("192x192", sizes, "Android install needs a 192px icon")
        self.assertIn("512x512", sizes, "Android install needs a 512px icon")
        for icon in data["icons"]:
            self.assertTrue(
                (self.static_dir / icon["src"]).is_file(),
                f"missing icon file {icon['src']}",
            )

    def test_service_worker_is_served_from_the_site_root(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/javascript", response["Content-Type"])
        # Root scope, so one worker covers every page.
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("addEventListener", response.content.decode())

    def test_entering_a_room_offers_the_home_screen_prompt(self):
        self.enter_room()
        page = self.client.get(reverse("room_directory", args=[self.room.id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'rel="manifest"')
        self.assertContains(page, "apple-touch-icon")
        self.assertContains(page, 'id="install-sheet"')
        self.assertContains(page, "install.js")
        self.assertContains(page, "Add to Home Screen")


class LeaderAvatarTests(ChatTestBase):
    """One photo field, and a row pointing at a lost file must not break pages."""

    def test_leader_has_a_single_photo_field(self):
        field_names = {f.name for f in Leader._meta.get_fields()}
        self.assertIn("avatar", field_names)
        self.assertNotIn("photo", field_names)

    def test_avatar_url_is_empty_when_the_file_is_gone(self):
        self.leader.avatar = "leaders/does-not-exist.jpeg"
        self.leader.save(update_fields=["avatar"])
        self.assertEqual(self.leader.avatar_url, "")

        self.enter_room()
        page = self.client.get(reverse("room_directory", args=[self.room.id]))
        self.assertEqual(page.status_code, 200)
        # Falls back to initials instead of a broken <img>.
        self.assertNotContains(page, "leaders/does-not-exist.jpeg")
        self.assertContains(page, "TL")

    def test_avatar_url_is_returned_when_the_file_exists(self):
        import shutil
        import tempfile
        from django.core.files.base import ContentFile
        from django.test import override_settings

        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, True)
        with override_settings(MEDIA_ROOT=media_root):
            self.leader.avatar.save(
                "photo.png", ContentFile(b"\x89PNG\r\n\x1a\n"), save=True
            )
            leader = Leader.objects.get(pk=self.leader.pk)
            self.assertEqual(leader.avatar_url, leader.avatar.url)
            self.assertTrue(leader.avatar_url.startswith(settings.MEDIA_URL))


class AnonBoardTests(TestCase):
    """anonboard: anyone can post a problem and reply without an account."""

    def test_board_page_renders(self):
        page = self.client.get(reverse("anon_board"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "anonboard")

    def test_posting_a_problem_opens_its_thread(self):
        response = self.client.post(
            reverse("anon_board"),
            {"title": "Exam stress", "body": "I cannot sleep before tests."},
        )
        post = BoardPost.objects.get()
        self.assertRedirects(
            response, reverse("anon_board_post", args=[post.id])
        )
        page = self.client.get(reverse("anon_board_post", args=[post.id]))
        self.assertContains(page, "I cannot sleep before tests.")

    def test_replies_appear_and_bump_the_post(self):
        post = BoardPost.objects.create(body="First problem")
        self.client.post(
            reverse("anon_board_post", args=[post.id]), {"body": "You are not alone."}
        )
        self.assertEqual(BoardComment.objects.filter(post=post).count(), 1)
        page = self.client.get(reverse("anon_board_post", args=[post.id]))
        self.assertContains(page, "You are not alone.")

    def test_a_blank_problem_is_rejected(self):
        self.client.post(reverse("anon_board"), {"title": "x", "body": "   "})
        self.assertEqual(BoardPost.objects.count(), 0)

    def test_every_post_gets_its_own_alias(self):
        BoardPost.objects.create(body="one")
        BoardPost.objects.create(body="two")
        aliases = set(BoardPost.objects.values_list("alias", flat=True))
        self.assertEqual(len(aliases), 2)

    def test_hidden_posts_are_not_listed_or_reachable(self):
        post = BoardPost.objects.create(body="hidden problem", is_hidden=True)
        page = self.client.get(reverse("anon_board"))
        self.assertNotContains(page, "hidden problem")
        self.assertEqual(
            self.client.get(
                reverse("anon_board_post", args=[post.id])
            ).status_code,
            404,
        )
