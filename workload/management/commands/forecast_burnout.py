"""Forecast burnout risk for employees who have recent workload scores.

    python manage.py forecast_burnout [--horizon 14] [--top 20]

Ranks employees by projected score and flags those trending toward burnout.
Also updates the Prometheus burnout-risk gauge.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from workload.metrics import record_forecast, set_burnout_risk_count
from workload.models import WorkloadScore
from workload.services.forecast import forecast_burnout


class Command(BaseCommand):
    help = "Project workload scores ahead and flag employees trending to burnout."

    def add_arguments(self, parser):
        parser.add_argument("--horizon", type=int, default=14)
        parser.add_argument("--top", type=int, default=20)

    def handle(self, *args, **opts):
        user_ids = list(
            WorkloadScore.objects.values_list("user_id", flat=True).distinct()
        )
        forecasts = []
        for uid in user_ids:
            fc = forecast_burnout(uid, horizon_days=opts["horizon"])
            record_forecast(fc.projected_level or "NONE")
            forecasts.append(fc)

        set_burnout_risk_count(
            WorkloadScore.objects.filter(level__in=["HIGH", "BURNOUT_RISK"])
            .values("user_id")
            .distinct()
            .count()
        )

        forecasts.sort(key=lambda f: (f.projected_score or -1), reverse=True)
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"{len(forecasts)} employee(s), horizon {opts['horizon']}d"
            )
        )
        for fc in forecasts[: opts["top"]]:
            style = self.style.ERROR if fc.trending_to_burnout else self.style.SUCCESS
            proj = f"{fc.projected_score:.0f}" if fc.projected_score is not None else "—"
            self.stdout.write(
                style(
                    f"  user {fc.user_id}: proj={proj}/100 "
                    f"({fc.projected_level}) slope={fc.slope_per_day:+.2f}/d "
                    f"{'⚠ trending' if fc.trending_to_burnout else ''}"
                )
            )
