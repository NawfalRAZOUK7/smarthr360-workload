"""Module 1 tests: scoring engine correctness + API authorization."""

import time
from datetime import date, timedelta

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


def bearer(user_id, role="EMPLOYEE"):
    token = jwt.encode(
        {
            "token_type": "access",
            "user_id": user_id,
            "email": f"u{user_id}@corp.com",
            "role": role,
            "groups": [],
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

    def test_alert_acknowledge_flow(self):
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
