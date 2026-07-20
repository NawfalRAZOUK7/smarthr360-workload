"""Module 1 tests: scoring engine correctness + API authorization."""

import time
from datetime import date, timedelta
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import TestCase, override_settings

from smarthr360_jwt_auth import conf

from ..models import Task, WorkdaySignal, WorkloadAlert, WorkloadScore
from ..services import scoring

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PUBLIC_PEM = (
    _key.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def bearer(user_id, role="EMPLOYEE", groups=None):
    token = jwt.encode(
        {
            "token_type": "access",
            "user_id": user_id,
            "email": f"u{user_id}@corp.com",
            "role": role,
            "groups": groups or [],
            "iss": "smarthr360",
            "exp": int(time.time()) + 300,
        },
        PRIVATE_PEM,
        algorithm="RS256",
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class BaseCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._s = override_settings(
            SMARTHR_JWT_AUTH={"PUBLIC_KEY": PUBLIC_PEM, "ISSUER": "smarthr360"}
        )
        cls._s.enable()
        conf.clear_cache()

    @classmethod
    def tearDownClass(cls):
        cls._s.disable()
        conf.clear_cache()
        super().tearDownClass()


class ScoringEngineTests(BaseCase):
    def test_idle_user_scores_ok(self):
        result = scoring.compute_score(1)
        self.assertEqual(result.score, 0)
        self.assertEqual(result.level, WorkloadScore.Level.OK)
        self.assertIsNone(result.alert)

    def test_overloaded_user_triggers_burnout_alert(self):
        today = date.today()
        for i in range(8):
            Task.objects.create(
                user_id=2,
                title=f"task-{i}",
                estimated_hours=6,
                complexity=5,
                deadline=today + timedelta(days=1),
                is_unplanned=(i % 2 == 0),
            )
        WorkdaySignal.objects.create(
            user_id=2, date=today, meetings_count=6,
            interruptions_count=8, stress_level=5,
        )
        result = scoring.compute_score(2)
        self.assertGreaterEqual(result.score, 85)
        self.assertEqual(result.level, WorkloadScore.Level.BURNOUT_RISK)
        self.assertIsNotNone(result.alert)
        self.assertEqual(result.alert.level, WorkloadAlert.Level.CRITICAL)
        self.assertTrue(result.alert.recommendations)

    def test_components_are_bounded_and_explainable(self):
        Task.objects.create(user_id=3, title="t", estimated_hours=1000, complexity=5)
        c = scoring.compute_components(3)
        self.assertLessEqual(c["volume"], 1.0)
        for key in ("volume", "complexity", "deadlines", "interruptions", "stress"):
            self.assertIn(key, c)

    def test_done_tasks_do_not_count(self):
        Task.objects.create(
            user_id=4, title="done", estimated_hours=40,
            complexity=5, status=Task.Status.DONE,
        )
        self.assertEqual(scoring.compute_components(4)["open_hours"], 0)


class WorkloadAPITests(BaseCase):
    def test_employee_task_crud_and_scoping(self):
        resp = self.client.post(
            "/api/workload/tasks/",
            {"title": "Write report", "estimated_hours": 4, "complexity": 3},
            content_type="application/json",
            **bearer(10),
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["user_id"], 10)

        # another employee cannot see it
        other = self.client.get("/api/workload/tasks/", **bearer(11))
        self.assertEqual(other.json()["meta"]["count"], 0)

    def test_employee_cannot_assign_to_others_manager_can(self):
        denied = self.client.post(
            "/api/workload/tasks/",
            {"title": "x", "user_id": 99},
            content_type="application/json",
            **bearer(10),
        )
        self.assertEqual(denied.status_code, 403)

        ok = self.client.post(
            "/api/workload/tasks/",
            {"title": "x", "user_id": 99},
            content_type="application/json",
            **bearer(1, "MANAGER"),
        )
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["created_by_user_id"], 1)

    @mock.patch("workload.clients.CoreHRClient.get_my_team_user_ids")
    def test_manager_task_list_scoped_to_team(self, mock_team):
        # A manager sees only their direct reports' tasks (+ their own),
        # not every user's — row-level scoping via the core-hr team roster.
        mock_team.return_value = [10, 11]
        Task.objects.create(user_id=10, title="a", estimated_hours=4)
        Task.objects.create(user_id=11, title="b", estimated_hours=4)
        Task.objects.create(user_id=99, title="c", estimated_hours=4)  # not on team

        resp = self.client.get("/api/workload/tasks/", **bearer(1, "MANAGER"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["count"], 2)  # 10 & 11 only, not 99

        # explicitly requesting an out-of-team user returns nothing
        outside = self.client.get(
            "/api/workload/tasks/?user_id=99", **bearer(1, "MANAGER")
        )
        self.assertEqual(outside.json()["meta"]["count"], 0)

    def test_hr_task_list_is_unrestricted(self):
        Task.objects.create(user_id=10, title="a", estimated_hours=4)
        Task.objects.create(user_id=99, title="c", estimated_hours=4)
        resp = self.client.get("/api/workload/tasks/", **bearer(1, "HR"))
        self.assertEqual(resp.json()["meta"]["count"], 2)

    def _make_alert(self, user_id):
        score = WorkloadScore.objects.create(
            user_id=user_id, score=90.0, level="BURNOUT_RISK"
        )
        return WorkloadAlert.objects.create(
            user_id=user_id, score=score, level="CRITICAL", message="overloaded"
        )

    @mock.patch("workload.clients.CoreHRClient.get_my_team_user_ids")
    def test_manager_alert_list_scoped_to_team(self, mock_team):
        # Overload alerts follow the same team-scoping as tasks.
        mock_team.return_value = [10, 11]
        for uid in (10, 11, 99):
            self._make_alert(uid)
        resp = self.client.get("/api/workload/alerts/", **bearer(1, "MANAGER"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["count"], 2)  # 10 & 11, not 99

    def test_hr_alert_list_is_unrestricted(self):
        for uid in (10, 99):
            self._make_alert(uid)
        resp = self.client.get("/api/workload/alerts/", **bearer(1, "HR"))
        self.assertEqual(resp.json()["meta"]["count"], 2)

    def test_compute_and_read_score(self):
        Task.objects.create(user_id=20, title="t", estimated_hours=30, complexity=4)
        resp = self.client.post("/api/workload/scores/compute/", **bearer(20))
        self.assertEqual(resp.status_code, 201)
        self.assertGreater(resp.json()["score"], 0)

        scores = self.client.get("/api/workload/scores/", **bearer(20))
        self.assertEqual(scores.json()["meta"]["count"], 1)

    def test_signals_are_self_reported(self):
        resp = self.client.post(
            "/api/workload/signals/",
            {"date": str(date.today()), "meetings_count": 3, "stress_level": 4},
            content_type="application/json",
            **bearer(30),
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(WorkdaySignal.objects.get().user_id, 30)

    def test_team_overview_manager_only(self):
        self.assertEqual(
            self.client.get("/api/workload/team-overview/", **bearer(5)).status_code,
            403,
        )
        Task.objects.create(user_id=6, title="t", estimated_hours=8)
        scoring.compute_score(6)
        resp = self.client.get(
            "/api/workload/team-overview/?user_ids=6", **bearer(1, "HR")
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["team"][0]["user_id"], 6)
        self.assertIsNotNone(resp.json()["team"][0]["score"])

    @mock.patch("workload.clients.CoreHRClient.get_my_team_user_ids")
    def test_alert_acknowledge_flow(self, mock_team):
        # Manager acknowledging is now team-scoped: user 40 is on their team.
        mock_team.return_value = [40]
        today = date.today()
        for i in range(8):
            Task.objects.create(
                user_id=40, title=f"t{i}", estimated_hours=6, complexity=5,
                deadline=today, is_unplanned=True,
            )
        WorkdaySignal.objects.create(
            user_id=40, date=today, meetings_count=8,
            interruptions_count=8, stress_level=5,
        )
        scoring.compute_score(40)
        alert_id = WorkloadAlert.objects.get(user_id=40).id

        denied = self.client.post(
            f"/api/workload/alerts/{alert_id}/acknowledge/", **bearer(40)
        )
        self.assertEqual(denied.status_code, 403)

        ok = self.client.post(
            f"/api/workload/alerts/{alert_id}/acknowledge/", **bearer(2, "MANAGER")
        )
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["acknowledged"])


class RetentionWiringTests(BaseCase):
    """Burnout alerts notify the retention service (mocked client)."""

    def _overload(self, user_id):
        today = date.today()
        for i in range(8):
            Task.objects.create(
                user_id=user_id, title=f"t{i}", estimated_hours=6,
                complexity=5, deadline=today, is_unplanned=True,
            )
        WorkdaySignal.objects.create(
            user_id=user_id, date=today, meetings_count=8,
            interruptions_count=8, stress_level=5,
        )

    @mock.patch("workload.clients.RetentionClient.notify_burnout")
    def test_burnout_alert_notifies_retention(self, mock_notify):
        mock_notify.return_value = True
        self._overload(70)
        resp = self.client.post("/api/workload/scores/compute/", **bearer(70))
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["retention_notified"])
        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        self.assertEqual(kwargs["user_id"], 70)
        self.assertGreaterEqual(kwargs["intensity"], 85)

    @mock.patch("workload.clients.RetentionClient.notify_burnout")
    def test_healthy_score_does_not_notify(self, mock_notify):
        resp = self.client.post("/api/workload/scores/compute/", **bearer(71))
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.json()["retention_notified"])
        mock_notify.assert_not_called()

    @mock.patch("workload.clients.SESSION.post")
    def test_retention_outage_never_breaks_scoring(self, mock_post):
        import requests as _requests

        mock_post.side_effect = _requests.ConnectionError("down")
        self._overload(72)
        resp = self.client.post("/api/workload/scores/compute/", **bearer(72))
        self.assertEqual(resp.status_code, 201)          # scoring unaffected
        self.assertFalse(resp.json()["retention_notified"])


class AlertEmailTests(BaseCase):
    """Burnout alerts email the affected employee (+HR on CRITICAL)."""

    @mock.patch("workload.clients.RetentionClient.notify_burnout")
    def test_critical_alert_emails_employee_and_hr_inbox(self, mock_notify):
        import os
        from django.core import mail

        mock_notify.return_value = True
        today = date.today()
        for i in range(8):
            Task.objects.create(
                user_id=80, title=f"t{i}", estimated_hours=6, complexity=5,
                deadline=today, is_unplanned=True,
            )
        WorkdaySignal.objects.create(
            user_id=80, date=today, meetings_count=8,
            interruptions_count=8, stress_level=5,
        )
        os.environ["WORKLOAD_HR_EMAIL"] = "hr-alerts@corp.com"
        try:
            resp = self.client.post(
                "/api/workload/scores/compute/", **bearer(80)
            )
        finally:
            del os.environ["WORKLOAD_HR_EMAIL"]
        self.assertTrue(resp.json()["email_sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("u80@corp.com", mail.outbox[0].to)
        self.assertIn("hr-alerts@corp.com", mail.outbox[0].to)
        self.assertIn("CRITICAL", mail.outbox[0].subject)

    @mock.patch("workload.clients.RetentionClient.notify_burnout")
    def test_no_alert_no_email(self, mock_notify):
        from django.core import mail

        resp = self.client.post("/api/workload/scores/compute/", **bearer(81))
        self.assertFalse(resp.json()["email_sent"])
        self.assertEqual(len(mail.outbox), 0)
        mock_notify.assert_not_called()


class TrendAndRebalancingTests(BaseCase):
    def test_score_trend_direction(self):
        for hours in (5, 20, 45):
            Task.objects.all().delete()
            Task.objects.create(user_id=90, title="t", estimated_hours=hours,
                                complexity=3)
            scoring.compute_score(90)
        resp = self.client.get("/api/workload/scores/trend/", **bearer(90))
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["points"], 3)
        self.assertEqual(body["direction"], "worsening")

    def test_rebalancing_names_least_loaded_teammate(self):
        Task.objects.create(user_id=1, title="big", estimated_hours=40,
                            complexity=3)
        Task.objects.create(user_id=1, title="todo", estimated_hours=4,
                            complexity=1)
        Task.objects.create(user_id=2, title="light", estimated_hours=6,
                            complexity=2)
        Task.objects.create(user_id=3, title="medium", estimated_hours=20,
                            complexity=2)

        denied = self.client.get(
            "/api/workload/rebalancing/?user_ids=1,2,3", **bearer(9)
        )
        self.assertEqual(denied.status_code, 403)

        resp = self.client.get(
            "/api/workload/rebalancing/?user_ids=1,2,3",
            **bearer(5, "MANAGER"),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["team_source"], "query")
        s = body["suggestions"][0]
        self.assertEqual(s["overloaded_user_id"], 1)
        self.assertEqual(s["suggested_recipient_user_id"], 2)  # 6h < 20h
        self.assertTrue(s["tasks_to_move"])

    @mock.patch("workload.clients.CoreHRClient.get_my_team_user_ids")
    def test_rebalancing_pulls_team_from_core_hr(self, mock_team):
        mock_team.return_value = [11, 12]
        Task.objects.create(user_id=11, title="huge", estimated_hours=50,
                            complexity=4, status=Task.Status.TODO)
        resp = self.client.get(
            "/api/workload/rebalancing/", **bearer(5, "MANAGER")
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["team_source"], "core-hr my-team")
        self.assertEqual(
            resp.json()["suggestions"][0]["suggested_recipient_user_id"], 12
        )


class ScheduledScoringCommandTests(BaseCase):
    @mock.patch("workload.clients.RetentionClient.notify_burnout")
    def test_command_scores_everyone_and_digests_critical(self, _):
        import os
        from io import StringIO

        from django.core import mail
        from django.core.management import call_command

        today = date.today()
        Task.objects.create(user_id=60, title="light", estimated_hours=4,
                            complexity=2)
        for i in range(8):
            Task.objects.create(user_id=61, title=f"t{i}", estimated_hours=6,
                                complexity=5, deadline=today,
                                is_unplanned=True)
        WorkdaySignal.objects.create(user_id=61, date=today, meetings_count=8,
                                     interruptions_count=8, stress_level=5)

        os.environ["WORKLOAD_HR_EMAIL"] = "hr-digest@corp.com"
        out = StringIO()
        try:
            call_command("compute_all_scores", stdout=out)
        finally:
            del os.environ["WORKLOAD_HR_EMAIL"]

        self.assertIn("scored=2 critical=1", out.getvalue())
        self.assertEqual(WorkloadScore.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("hr-digest@corp.com", mail.outbox[0].to)
        self.assertIn("user_id=61", mail.outbox[0].body)


class AuditorReadOnlyTests(BaseCase):
    """The AUDITOR group (public demo guest) must never write.

    Enforced by smarthr360_jwt_auth.readonly.AuditorReadOnlyMiddleware. These
    endpoints are self-scoped, so a plain EMPLOYEE may legitimately write to
    them — which is exactly why the auditor rule cannot live in the per-view
    permission classes here.
    """

    WRITE_ENDPOINTS = (
        "/api/workload/tasks/",
        "/api/workload/signals/",
        "/api/workload/scores/compute/",
    )

    def test_auditor_cannot_write(self):
        for url in self.WRITE_ENDPOINTS:
            with self.subTest(url=url):
                resp = self.client.post(
                    url,
                    data="{}",
                    content_type="application/json",
                    **bearer(28, "EMPLOYEE", groups=["EMPLOYEE", "AUDITOR"]),
                )
                self.assertEqual(resp.status_code, 403, f"{url} allowed an auditor write")

    def test_auditor_can_still_read(self):
        resp = self.client.get(
            "/api/workload/tasks/",
            **bearer(28, "EMPLOYEE", groups=["EMPLOYEE", "AUDITOR"]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_plain_employee_write_is_unaffected(self):
        """Guard against the fix over-reaching into normal employee access."""
        resp = self.client.post(
            "/api/workload/scores/compute/",
            data="{}",
            content_type="application/json",
            **bearer(29, "EMPLOYEE"),
        )
        self.assertEqual(resp.status_code, 201)

    def test_admin_write_is_unaffected(self):
        """is_auditor() is true for admins too; they must not be locked out."""
        resp = self.client.post(
            "/api/workload/scores/compute/",
            data="{}",
            content_type="application/json",
            **bearer(1, "ADMIN"),
        )
        self.assertEqual(resp.status_code, 201)
