from django.core.management import call_command
from django.test import TestCase

from workload.models import Task, WorkloadAlert, WorkloadScore


class SeedDemoTests(TestCase):
    def test_seed_demo_is_idempotent(self):
        call_command("seed_demo")
        first = (Task.objects.count(), WorkloadScore.objects.count(), WorkloadAlert.objects.count())
        call_command("seed_demo")
        self.assertEqual((Task.objects.count(), WorkloadScore.objects.count(), WorkloadAlert.objects.count()), first)
