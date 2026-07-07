"""Workload domain models (Module 1 — mental workload calculator).

Redesigned from the legacy `calcul_charge` prototype following the
functional spec (rapport §3.2): work volume, cognitive complexity,
deadline pressure, interruptions/meetings and self-reported stress feed
a scoring algorithm that triggers burnout-risk alerts.

Identity: `user_id` values from smarthr360-auth (ADR-005) — no local
user table.
"""

from django.db import models

from smarthr360_integration.history import SCD2HistoryBase


class Task(models.Model):
    """A unit of work assigned to an employee."""

    class Status(models.TextChoices):
        TODO = "TODO", "To do"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        DONE = "DONE", "Done"
        CANCELLED = "CANCELLED", "Cancelled"

    user_id = models.PositiveBigIntegerField(db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.TODO
    )

    estimated_hours = models.FloatField(default=1.0)
    complexity = models.PositiveSmallIntegerField(
        default=2, help_text="Cognitive complexity 1 (routine) – 5 (very complex)"
    )
    deadline = models.DateField(null=True, blank=True)
    is_unplanned = models.BooleanField(
        default=False, help_text="Unexpected task (legacy TacheImprevue)"
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Calibrated-task reference (legacy TacheCalibree)",
    )

    created_by_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline", "-created_at"]

    OPEN_STATUSES = (Status.TODO, Status.IN_PROGRESS)

    def __str__(self):
        return f"{self.title} ({self.status})"


class WorkdaySignal(models.Model):
    """Daily self-/system-reported context signals for one employee."""

    user_id = models.PositiveBigIntegerField(db_index=True)
    date = models.DateField()

    meetings_count = models.PositiveSmallIntegerField(default=0)
    interruptions_count = models.PositiveSmallIntegerField(default=0)
    stress_level = models.PositiveSmallIntegerField(
        default=3, help_text="Self-reported stress 1 (calm) – 5 (overwhelmed)"
    )
    comment = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user_id", "date")
        ordering = ["-date"]


class WorkloadScore(models.Model):
    """Computed mental-workload score for one employee at one moment."""

    class Level(models.TextChoices):
        OK = "OK", "Sustainable"
        ELEVATED = "ELEVATED", "Elevated"
        HIGH = "HIGH", "High"
        BURNOUT_RISK = "BURNOUT_RISK", "Burnout risk"

    user_id = models.PositiveBigIntegerField(db_index=True)
    score = models.FloatField(help_text="0 (idle) – 100 (critical)")
    level = models.CharField(max_length=20, choices=Level.choices)
    components = models.JSONField(
        default=dict, help_text="Per-dimension contributions used in the score."
    )
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-computed_at"]

    def __str__(self):
        return f"user {self.user_id}: {self.score:.0f} ({self.level})"


class WorkloadAlert(models.Model):
    """Alert raised when a score crosses the risk thresholds."""

    class Level(models.TextChoices):
        WARNING = "WARNING", "Warning"
        CRITICAL = "CRITICAL", "Critical"

    user_id = models.PositiveBigIntegerField(db_index=True)
    score = models.ForeignKey(
        WorkloadScore, on_delete=models.CASCADE, related_name="alerts"
    )
    level = models.CharField(max_length=20, choices=Level.choices)
    message = models.TextField()
    recommendations = models.JSONField(default=list)
    acknowledged = models.BooleanField(default=False)
    acknowledged_by_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class WorkloadLevelHistory(SCD2HistoryBase):
    """SCD Type 2 timeline of an employee's workload *level* transitions.

    Uses the shared ``SCD2HistoryBase`` (smarthr360-integration) — no history
    logic is re-implemented here. One open row per employee tracks how long they
    have been at a given band (OK / ELEVATED / HIGH / BURNOUT_RISK), enabling
    BI like "days spent at burnout risk" and trend context for the forecast.
    """

    employee_user_id = models.PositiveBigIntegerField(db_index=True)
    level = models.CharField(max_length=20)

    #: Owner identity used by snapshot_history to find the open row.
    SCD2_OWNER_FIELDS = ("employee_user_id",)

    class Meta:
        ordering = ["employee_user_id", "-date_debut"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee_user_id"],
                condition=models.Q(date_fin__isnull=True),
                name="uniq_open_workload_level_per_employee",
            ),
            models.UniqueConstraint(
                fields=["employee_user_id", "version"],
                name="uniq_workload_level_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee_user_id", "is_current"],
                name="wl_levelhist_emp_curr_idx",
            ),
        ]

    @property
    def tracked_snapshot(self) -> dict:
        return {"level": self.level}

    def __str__(self):
        end = self.date_fin.date() if self.date_fin else "present"
        return f"user {self.employee_user_id} {self.level} [v{self.version} →{end}]"
