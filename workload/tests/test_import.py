"""Tests for the workload task bulk-import (feed the burnout model)."""

from django.test import TestCase, override_settings

from smarthr360_jwt_auth import conf

from ..models import Task
from .test_scoring_and_api import PUBLIC_PEM, bearer


class TaskImportTests(TestCase):
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

    def test_manager_imports_tasks(self):
        payload = {
            "tasks": [
                {"user_id": 5, "title": "Ship export", "estimated_hours": 12, "complexity": 4},
                {"user_id": 5, "title": "Fix flaky test", "estimated_hours": 3, "complexity": 2, "status": "IN_PROGRESS"},
                {"user_id": 7, "title": "Onboarding doc", "estimated_hours": 4},
            ]
        }
        r = self.client.post(
            "/api/workload/tasks/import/", payload,
            content_type="application/json", **bearer(1, role="MANAGER"),
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["created"], 3)
        self.assertEqual(body["errors"], [])
        self.assertEqual(Task.objects.count(), 3)
        # complexity default applied + clamped
        self.assertEqual(Task.objects.get(title="Onboarding doc").complexity, 2)

    def test_bad_rows_are_reported_not_fatal(self):
        payload = {"tasks": [
            {"user_id": 5, "title": "ok"},
            {"user_id": "notanint", "title": "bad"},
            {"user_id": 5, "title": ""},  # missing title
        ]}
        r = self.client.post(
            "/api/workload/tasks/import/", payload,
            content_type="application/json", **bearer(1, role="MANAGER"),
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(len(body["errors"]), 2)

    def test_rbac(self):
        payload = {"tasks": [{"user_id": 5, "title": "x"}]}
        self.assertEqual(
            self.client.post("/api/workload/tasks/import/", payload,
                             content_type="application/json", **bearer(9, role="EMPLOYEE")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/workload/tasks/import/", payload,
                             content_type="application/json").status_code,
            401,
        )

    def test_empty_list_rejected(self):
        r = self.client.post(
            "/api/workload/tasks/import/", {"tasks": []},
            content_type="application/json", **bearer(1, role="MANAGER"),
        )
        self.assertEqual(r.status_code, 400)
