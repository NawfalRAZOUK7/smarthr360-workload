from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from workload.models import Task, WorkdaySignal, WorkloadAlert, WorkloadScore


class Command(BaseCommand):
    help = "Seed deterministic workload demo tasks, scores, and alerts."

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.localdate()
        plans = {
            4: (("Ship employee self-service", 8, 3), ("Resolve payroll integration", 6, 4)),
            7: (("Validate churn features", 7, 4), ("Present model review", 3, 3)),
            8: (("Upgrade production cluster", 12, 5), ("Incident follow-up", 5, 5)),
        }
        for user_id, tasks in plans.items():
            for title, hours, complexity in tasks:
                Task.objects.update_or_create(user_id=user_id, title=title, defaults={"status": "IN_PROGRESS", "estimated_hours": hours, "complexity": complexity, "deadline": today + timedelta(days=3), "created_by_user_id": 3})
            WorkdaySignal.objects.update_or_create(user_id=user_id, date=today, defaults={"meetings_count": 3 if user_id != 8 else 7, "interruptions_count": 4 if user_id != 8 else 10, "stress_level": 3 if user_id == 4 else 5, "comment": "Demo workload pulse"})

        for user_id, score, level in ((4, 46.0, "ELEVATED"), (7, 72.0, "HIGH"), (8, 91.0, "BURNOUT_RISK")):
            marker = {"seed": "coherent-demo", "task_load": round(score * 0.55, 1), "pressure": round(score * 0.45, 1)}
            workload, _ = WorkloadScore.objects.get_or_create(user_id=user_id, components__seed="coherent-demo", defaults={"score": score, "level": level, "components": marker})
            if workload.score != score or workload.level != level:
                workload.score, workload.level, workload.components = score, level, marker
                workload.save(update_fields=["score", "level", "components"])
            if level in {"HIGH", "BURNOUT_RISK"}:
                WorkloadAlert.objects.update_or_create(score=workload, defaults={"user_id": user_id, "level": "CRITICAL" if level == "BURNOUT_RISK" else "WARNING", "message": "Demo workload threshold crossed.", "recommendations": ["Reprioritize deadlines", "Protect focus time"]})
        self.stdout.write(self.style.SUCCESS("Workload demo data ready."))
