"""Tests for the team workload CSV export (Phase 3)."""

from django.test import TestCase, override_settings

from smarthr360_jwt_auth import conf

from ..models import Task
from .test_scoring_and_api import PUBLIC_PEM, bearer


class WorkloadExportTests(TestCase):
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

    def setUp(self):
        Task.objects.create(user_id=5, title="Build export", estimated_hours=40, complexity=3)

    def test_export_csv_for_manager(self):
        resp = self.client.get("/api/workload/export/", **bearer(1, role="MANAGER"))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        body = resp.content.decode()
        self.assertIn("user_id,score,level,open_hours,computed_at", body)
        self.assertIn("5", body)  # the seeded user appears in the report

    def test_export_forbidden_for_employee(self):
        self.assertEqual(
            self.client.get("/api/workload/export/", **bearer(9, role="EMPLOYEE")).status_code,
            403,
        )

    def test_export_requires_auth(self):
        self.assertEqual(self.client.get("/api/workload/export/").status_code, 401)
