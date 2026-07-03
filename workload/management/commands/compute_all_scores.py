"""Scheduled scoring: compute every active user's workload score.

Run daily (k3s CronJob / cron):  python manage.py compute_all_scores

Scores + alerts are persisted exactly like user-triggered computes.
Cross-service side effects that need a user token (retention ingest,
employee email) are skipped here — the HR inbox (WORKLOAD_HR_EMAIL)
receives a digest of critical alerts instead.
"""

import os

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from workload.models import Task
from workload.services import scoring


class Command(BaseCommand):
    help = "Compute workload scores for every user with open tasks."

    def handle(self, *args, **options):
        user_ids = sorted(
            Task.objects.filter(status__in=Task.OPEN_STATUSES)
            .order_by()  # strip Meta.ordering: it breaks DISTINCT
            .values_list("user_id", flat=True)
            .distinct()
        )
        critical = []
        for user_id in user_ids:
            result = scoring.compute_score(user_id)
            marker = f" [{result.level}]" if result.alert else ""
            self.stdout.write(f"user {user_id}: {result.score}{marker}")
            if result.alert is not None and result.alert.level == "CRITICAL":
                critical.append((user_id, result.score))

        hr_inbox = os.environ.get("WORKLOAD_HR_EMAIL", "")
        if critical and hr_inbox:
            body = "\n".join(
                f"- user_id={uid}: score {score}" for uid, score in critical
            )
            send_mail(
                f"[SmartHR360] Scheduled scoring: {len(critical)} CRITICAL "
                f"workload alert(s)",
                f"Critical burnout-risk scores detected:\n{body}\n\n"
                "Details: /api/workload/alerts/",
                getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@smarthr360.dev"),
                [hr_inbox],
                fail_silently=True,
            )
        self.stdout.write(self.style.SUCCESS(
            f"scored={len(user_ids)} critical={len(critical)}"
        ))
