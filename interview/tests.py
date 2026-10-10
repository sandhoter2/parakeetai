"""
Tests for the interview app: models, API endpoints, session limits, billing.
Run with:  python manage.py test interview
"""
import json
import uuid
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import InterviewSession, UserProfile


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(username="alice", password="pw123", plan=UserProfile.PLAN_FREE):
    user = User.objects.create_user(username=username, password=password)
    # Signal already created UserProfile; update plan via queryset to avoid cache issues
    UserProfile.objects.filter(user=user).update(plan=plan)
    # Return a fresh instance with no cached reverse relations
    return User.objects.get(pk=user.pk)


def make_session(user, title="Test session", status=InterviewSession.STATUS_ACTIVE):
    return InterviewSession.objects.create(
        owner=user, title=title, status=status,
    )


# ─── Model tests ──────────────────────────────────────────────────────────────

class UserProfileTests(TestCase):
    def test_ext_token_generated_on_create(self):
        user = make_user()
        self.assertTrue(len(user.profile.ext_token) == 64)

    def test_free_plan_session_limit(self):
        user = make_user(plan=UserProfile.PLAN_FREE)
        self.assertEqual(user.profile.session_limit, 5)

    def test_pro_plan_no_limit(self):
        user = make_user(plan=UserProfile.PLAN_PRO)
        self.assertIsNone(user.profile.session_limit)

    def test_team_plan_no_limit(self):
        user = make_user(plan=UserProfile.PLAN_TEAM)
        self.assertIsNone(user.profile.session_limit)

    def test_regenerate_token_changes_value(self):
        user = make_user()
        old = user.profile.ext_token
        user.profile.regenerate_token()
        self.assertNotEqual(old, user.profile.ext_token)
        self.assertEqual(len(user.profile.ext_token), 64)

    def test_profile_auto_created_with_user(self):
        user = User.objects.create_user(username="bob", password="pw")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_default_theme_is_dark(self):
        user = make_user(username="theme_user")
        self.assertEqual(user.profile.theme, UserProfile.THEME_DARK)

    def test_theme_can_be_set_to_light(self):
        user = make_user(username="theme_user2")
        user.profile.theme = UserProfile.THEME_LIGHT
        user.profile.save()
        user.refresh_from_db()
        self.assertEqual(user.profile.theme, UserProfile.THEME_LIGHT)


class SessionLimitTests(TestCase):
    def test_free_user_under_limit(self):
        user = make_user(plan=UserProfile.PLAN_FREE)
        for i in range(4):
            make_session(user, title=f"s{i}")
        from .views import _check_session_limit
        ok, used, limit = _check_session_limit(user)
        self.assertTrue(ok)
        self.assertEqual(used, 4)
        self.assertEqual(limit, 5)

    def test_free_user_at_limit(self):
        user = make_user(plan=UserProfile.PLAN_FREE)
        for i in range(5):
            make_session(user, title=f"s{i}")
        from .views import _check_session_limit
        ok, used, limit = _check_session_limit(user)
        self.assertFalse(ok)
        self.assertEqual(used, 5)

    def test_pro_user_no_limit(self):
        user = make_user(plan=UserProfile.PLAN_PRO)
        for i in range(10):
            make_session(user, title=f"s{i}")
        from .views import _check_session_limit
        ok, used, limit = _check_session_limit(user)
        self.assertTrue(ok)
        self.assertIsNone(limit)


# ─── api_login ─────────────────────────────────────────────────────────────────

class ApiLoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user(username="logintest", password="secret99")

    def _post(self, body):
        return self.client.post(
            reverse("api_login"),
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_valid_login_returns_token(self):
        r = self._post({"username": "logintest", "password": "secret99"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("token", data)
        self.assertEqual(data["token"], self.user.profile.ext_token)
        self.assertEqual(data["plan"], UserProfile.PLAN_FREE)
        self.assertEqual(data["session_limit"], 5)
        self.assertEqual(data["sessions_used"], 0)

    def test_wrong_password_is_401(self):
        r = self._post({"username": "logintest", "password": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_missing_fields_is_400(self):
        r = self._post({"username": "logintest"})
        self.assertEqual(r.status_code, 400)

    def test_sessions_used_counted(self):
        make_session(self.user)
        make_session(self.user)
        r = self._post({"username": "logintest", "password": "secret99"})
        self.assertEqual(r.json()["sessions_used"], 2)


# ─── api_config ────────────────────────────────────────────────────────────────

class ApiConfigTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user(username="cfg_user", password="pw")
        self.other = make_user(username="cfg_other", password="pw")

    def _get(self, token):
        return self.client.get(
            reverse("api_config"),
            HTTP_X_EXT_TOKEN=token,
        )

    def test_returns_own_sessions_only(self):
        s1 = make_session(self.user, "mine")
        make_session(self.other, "theirs")  # should NOT appear
        r = self._get(self.user.profile.ext_token)
        self.assertEqual(r.status_code, 200)
        ids = [s["id"] for s in r.json()["active_sessions"]]
        self.assertIn(str(s1.id), ids)
        self.assertEqual(len(ids), 1)

    def test_invalid_token_is_401(self):
        r = self._get("bad-token-xyz")
        self.assertEqual(r.status_code, 401)

    def test_latest_session_id_is_own(self):
        s = make_session(self.user, "latest mine")
        make_session(self.other, "latest theirs")
        r = self._get(self.user.profile.ext_token)
        self.assertEqual(r.json()["latest_session_id"], str(s.id))


# ─── api_new_session ───────────────────────────────────────────────────────────

class ApiNewSessionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user(username="new_sess", password="pw", plan=UserProfile.PLAN_FREE)

    def _post(self, token, body=None):
        return self.client.post(
            reverse("api_new_session"),
            data=json.dumps(body or {}),
            content_type="application/json",
            HTTP_X_EXT_TOKEN=token,
        )

    def test_creates_session_and_returns_id(self):
        r = self._post(self.user.profile.ext_token, {"title": "My Interview"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("session_id", data)
        self.assertTrue(InterviewSession.objects.filter(id=data["session_id"]).exists())

    def test_default_title_when_blank(self):
        r = self._post(self.user.profile.ext_token, {})
        self.assertEqual(r.status_code, 200)
        sid = r.json()["session_id"]
        s = InterviewSession.objects.get(id=sid)
        self.assertTrue(s.title)

    def test_session_belongs_to_user(self):
        r = self._post(self.user.profile.ext_token, {"title": "Owned"})
        sid = r.json()["session_id"]
        s = InterviewSession.objects.get(id=sid)
        self.assertEqual(s.owner, self.user)

    def test_enforces_free_limit(self):
        for i in range(5):
            make_session(self.user, title=f"s{i}")
        r = self._post(self.user.profile.ext_token, {"title": "one too many"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "session_limit_reached")

    def test_pro_user_exceeds_five(self):
        self.user.profile.plan = UserProfile.PLAN_PRO
        self.user.profile.save()
        for i in range(10):
            make_session(self.user, title=f"s{i}")
        r = self._post(self.user.profile.ext_token, {"title": "eleventh"})
        self.assertEqual(r.status_code, 200)

    def test_invalid_token_is_401(self):
        r = self._post("bad-token")
        self.assertEqual(r.status_code, 401)


# ─── URL routing ──────────────────────────────────────────────────────────────

class UrlRoutingTests(TestCase):
    def test_api_login_resolves(self):
        self.assertEqual(reverse("api_login"), "/api/login/")

    def test_api_new_session_resolves(self):
        self.assertEqual(reverse("api_new_session"), "/api/session/new/")

    def test_api_config_resolves(self):
        self.assertEqual(reverse("api_config"), "/api/config/")

    def test_home_resolves(self):
        self.assertEqual(reverse("home"), "/")

    def test_pricing_resolves(self):
        self.assertEqual(reverse("pricing"), "/pricing/")

    def test_api_theme_resolves(self):
        self.assertEqual(reverse("api_theme"), "/api/theme/")


class ThemeViewTests(TestCase):
    def setUp(self):
        self.user = make_user(username="themetester", password="pw")

    def test_toggle_theme_unauthenticated_redirects(self):
        r = self.client.post("/api/theme/", {"theme": "light"})
        self.assertEqual(r.status_code, 302)

    def test_toggle_theme_authenticated(self):
        self.client.login(username="themetester", password="pw")
        r = self.client.post("/api/theme/", {"theme": "light"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["theme"], "light")
        self.user.refresh_from_db()
        self.assertEqual(self.user.profile.theme, "light")

        # Toggle back
        r2 = self.client.post("/api/theme/", {})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["theme"], "dark")
        self.user.refresh_from_db()
        self.assertEqual(self.user.profile.theme, "dark")

