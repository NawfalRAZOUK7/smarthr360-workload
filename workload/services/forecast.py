"""Burnout forecast — project an employee's workload score ahead.

Uses the recent ``WorkloadScore`` time-series (already persisted at each
compute) and the shared least-squares trend (smarthr360-integration.analytics)
to project the score ``horizon_days`` ahead, classify the projected level and
flag employees trending toward burnout. Pure enough to unit-test: the analytic
core takes plain (timestamp, score) points.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Sequence

from django.utils import timezone

from smarthr360_integration.analytics import clamp, linear_trend, project

from ..models import WorkloadScore

# Same thresholds as the scoring engine, kept in sync via level_for().
_THRESHOLDS = (
    (85, "BURNOUT_RISK"),
    (70, "HIGH"),
    (50, "ELEVATED"),
    (0, "OK"),
)
DEFAULT_HORIZON_DAYS = 14
_MIN_POINTS = 3


def level_for(score: float) -> str:
    for threshold, level in _THRESHOLDS:
        if score >= threshold:
            return level
    return "OK"


@dataclass
class BurnoutForecast:
    user_id: int
    horizon_days: int
    current_score: Optional[float]
    slope_per_day: float
    projected_score: Optional[float]
    projected_level: Optional[str]
    trending_to_burnout: bool
    confidence: str
    rationale: str

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "horizon_days": self.horizon_days,
            "current_score": self.current_score,
            "slope_per_day": round(self.slope_per_day, 3),
            "projected_score": (
                round(self.projected_score, 1)
                if self.projected_score is not None
                else None
            ),
            "projected_level": self.projected_level,
            "trending_to_burnout": self.trending_to_burnout,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


def forecast_burnout(
    user_id: int,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    lookback_days: int = 60,
    now=None,
) -> BurnoutForecast:
    now = now or timezone.now()
    since = now - timedelta(days=lookback_days)

    scores = list(
        WorkloadScore.objects.filter(user_id=user_id, computed_at__gte=since)
        .order_by("computed_at")
        .values_list("computed_at", "score")
    )
    return _forecast_from_points(user_id, scores, horizon_days, now)


def _forecast_from_points(
    user_id: int, scores: Sequence, horizon_days: int, now
) -> BurnoutForecast:
    if not scores:
        return BurnoutForecast(
            user_id, horizon_days, None, 0.0, None, None, False, "none",
            "No recent workload scores to forecast from.",
        )

    # x in days relative to the first point; y = score.
    t0 = scores[0][0]
    points = [((dt - t0).total_seconds() / 86400.0, float(s)) for dt, s in scores]
    current = points[-1][1]
    slope = linear_trend(points)  # score units per day

    x_now = (now - t0).total_seconds() / 86400.0
    projected = clamp(project(current, slope, horizon_days), 0.0, 100.0)
    projected_level = level_for(projected)
    trending = projected_level in ("HIGH", "BURNOUT_RISK") and slope > 0

    if len(points) < _MIN_POINTS:
        confidence = "low"
    elif len(points) < 6:
        confidence = "medium"
    else:
        confidence = "high"

    if slope > 0.2:
        direction = f"rising {slope:.1f}/day"
    elif slope < -0.2:
        direction = f"easing {slope:.1f}/day"
    else:
        direction = "stable"
    rationale = (
        f"{len(points)} scores over the window; current {current:.0f}/100 "
        f"({direction}) -> projected {projected:.0f}/100 ({projected_level}) "
        f"in {horizon_days} days."
    )

    return BurnoutForecast(
        user_id=user_id,
        horizon_days=horizon_days,
        current_score=current,
        slope_per_day=slope,
        projected_score=projected,
        projected_level=projected_level,
        trending_to_burnout=trending,
        confidence=confidence,
        rationale=rationale,
    )
