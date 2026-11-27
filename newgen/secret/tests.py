import json

from django.conf import settings
from django.urls import reverse
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from newgen.asgi import application

from secret.models import Institution, Room, Leader, Anonymous, Conversation, Message


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
        self.leader.refresh_from_db()
        self.assertTrue(self.leader.check_password("brand-new-password-9"))
        self.assertTrue(self.leader.password.startswith("argon2$"))

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
