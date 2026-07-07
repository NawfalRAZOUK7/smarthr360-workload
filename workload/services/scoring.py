"""Mental-workload scoring engine (rapport SmartHR360 §3.2).

Five dimensions, each normalized to 0..1, combined with configurable
weights into a 0-100 score:

  volume        open estimated hours vs weekly capacity
  complexity    average cognitive complexity of open tasks (1-5)
  deadlines     share of open tasks due within DEADLINE_WINDOW days
  interruptions meetings + interruptions from the latest workday signal
  stress        self-reported stress level (1-5)

Thresholds: <50 OK · 50-70 ELEVATED · 70-85 HIGH · ≥85 BURNOUT_RISK.
HIGH and BURNOUT_RISK raise a WorkloadAlert with rebalancing
recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Sum

from smarthr360_integration.history import snapshot_history

from ..metrics import record_score
from ..models import (
    Task,
    WorkdaySignal,
    WorkloadAlert,
    WorkloadLevelHistory,
    WorkloadScore,
)

WEEKLY_CAPACITY_HOURS = 40.0
DEADLINE_WINDOW_DAYS = 3
UNPLANNED_PENALTY = 0.15  # extra weight for unplanned tasks in volume

WEIGHTS = {
    "volume": 0.30,
    "complexity": 0.20,
    "deadlines": 0.20,
    "interruptions": 0.15,
    "stress": 0.15,
}

THRESHOLDS = (
    (85, WorkloadScore.Level.BURNOUT_RISK),
    (70, WorkloadScore.Level.HIGH),
    (50, WorkloadScore.Level.ELEVATED),
    (0, WorkloadScore.Level.OK),
)


@dataclass
class ScoreResult:
    score: float
    level: str
    components: dict = field(default_factory=dict)
    alert: WorkloadAlert | None = None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_components(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    open_tasks = list(
        Task.objects.filter(user_id=user_id, status__in=Task.OPEN_STATUSES)
    )

    # volume
    hours = sum(t.estimated_hours for t in open_tasks)
    unplanned_hours = sum(t.estimated_hours for t in open_tasks if t.is_unplanned)
    volume = _clamp(
        (hours + UNPLANNED_PENALTY * unplanned_hours) / WEEKLY_CAPACITY_HOURS
    )

    # complexity
    complexity = (
        _clamp((sum(t.complexity for t in open_tasks) / len(open_tasks) - 1) / 4)
        if open_tasks
        else 0.0
    )

    # deadline pressure
    window_end = today + timedelta(days=DEADLINE_WINDOW_DAYS)
    due_soon = [t for t in open_tasks if t.deadline and t.deadline <= window_end]
    deadlines = _clamp(len(due_soon) / len(open_tasks)) if open_tasks else 0.0

    # interruptions & meetings (latest signal)
    signal = (
        WorkdaySignal.objects.filter(user_id=user_id).order_by("-date").first()
    )
    interruptions = (
        _clamp((signal.meetings_count + signal.interruptions_count) / 12)
        if signal
        else 0.0
    )

    # self-reported stress
    stress = _clamp((signal.stress_level - 1) / 4) if signal else 0.0

    return {
        "volume": round(volume, 3),
        "complexity": round(complexity, 3),
        "deadlines": round(deadlines, 3),
        "interruptions": round(interruptions, 3),
        "stress": round(stress, 3),
        "open_tasks": len(open_tasks),
        "open_hours": round(hours, 1),
        "due_soon": len(due_soon),
    }


def _level_for(score: float) -> str:
    for threshold, level in THRESHOLDS:
        if score >= threshold:
            return level
    return WorkloadScore.Level.OK


def _recommendations(components: dict) -> list[str]:
    recs = []
    if components["volume"] >= 0.8:
        recs.append(
            "Workload exceeds 80% of weekly capacity: postpone or delegate "
            "the lowest-priority tasks."
        )
    if components["deadlines"] >= 0.5:
        recs.append(
            "Half of open tasks are due within 3 days: renegotiate deadlines "
            "or split deliverables."
        )
    if components["interruptions"] >= 0.6:
        recs.append(
            "High interruption/meeting load: block focus time and decline "
            "non-essential meetings."
        )
    if components["complexity"] >= 0.7:
        recs.append(
            "Task mix is cognitively heavy: alternate complex and routine "
            "work, consider pairing."
        )
    if components["stress"] >= 0.75:
        recs.append(
            "Self-reported stress is high: manager check-in recommended; "
            "consider the wellbeing survey."
        )
    return recs or ["Monitor: no specific action required."]


def compute_score(user_id: int, today: date | None = None) -> ScoreResult:
    """Compute, persist and (if needed) alert for one employee."""
    components = compute_components(user_id, today)
    raw = sum(WEIGHTS[k] * components[k] for k in WEIGHTS)
    score = round(100 * raw, 1)
    level = _level_for(score)

    record = WorkloadScore.objects.create(
        user_id=user_id, score=score, level=level, components=components
    )

    alert = None
    if level in (WorkloadScore.Level.HIGH, WorkloadScore.Level.BURNOUT_RISK):
        alert = WorkloadAlert.objects.create(
            user_id=user_id,
            score=record,
            level=(
                WorkloadAlert.Level.CRITICAL
                if level == WorkloadScore.Level.BURNOUT_RISK
                else WorkloadAlert.Level.WARNING
            ),
            message=(
                f"Mental workload {score:.0f}/100 ({level}). "
                f"{components['open_tasks']} open tasks, "
                f"{components['open_hours']}h estimated, "
                f"{components['due_soon']} due within {DEADLINE_WINDOW_DAYS} days."
            ),
            recommendations=_recommendations(components),
        )

    # SCD2: record a new version only when the employee's *level* changes
    # (idempotent via the shared history service). Fed to BI + forecast context.
    snapshot_history(
        WorkloadLevelHistory,
        owner_filter={"employee_user_id": user_id},
        snapshot={"level": level},
        source_system="WORKLOAD",
    )
    # Prometheus: count computes by level (exposed on /metrics).
    record_score(level)

    return ScoreResult(score=score, level=level, components=components, alert=alert)


def team_overview(user_ids: list[int]) -> list[dict]:
    """Latest score per user id (for manager dashboards)."""
    out = []
    for uid in user_ids:
        latest = WorkloadScore.objects.filter(user_id=uid).first()
        open_hours = (
            Task.objects.filter(user_id=uid, status__in=Task.OPEN_STATUSES)
            .aggregate(h=Sum("estimated_hours"))["h"]
            or 0
        )
        out.append(
            {
                "user_id": uid,
                "score": latest.score if latest else None,
                "level": latest.level if latest else None,
                "open_hours": open_hours,
                "computed_at": latest.computed_at.isoformat() if latest else None,
            }
        )
    return out
