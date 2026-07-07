"""Prometheus metrics for workload, built on the shared observability factory.

No metric plumbing is re-implemented: ``get_counter``/``get_gauge`` come from
smarthr360-integration and are idempotent, so importing this module is safe on
autoreload. Exposed on the existing /metrics endpoint (django-prometheus).
"""

from __future__ import annotations

import time

from smarthr360_integration.observability import get_counter, get_gauge

WORKLOAD_SCORES = get_counter(
    "workload_scores_total",
    "Workload scores computed, by resulting level.",
    ["level"],
)

WORKLOAD_BURNOUT_RISK = get_gauge(
    "workload_burnout_risk_employees",
    "Employees currently at HIGH or BURNOUT_RISK level (latest score).",
)

WORKLOAD_FORECASTS = get_counter(
    "workload_forecasts_total",
    "Burnout forecasts produced, by projected level.",
    ["projected_level"],
)

WORKLOAD_FORECAST_LAST_RUN = get_gauge(
    "workload_forecast_last_run_timestamp_seconds",
    "Unix time of the last burnout forecast run.",
)


def record_score(level: str) -> None:
    try:
        WORKLOAD_SCORES.labels(level=level).inc()
    except Exception:  # pragma: no cover - never break scoring
        pass


def set_burnout_risk_count(count: int) -> None:
    try:
        WORKLOAD_BURNOUT_RISK.set(count)
    except Exception:  # pragma: no cover
        pass


def record_forecast(projected_level: str) -> None:
    try:
        WORKLOAD_FORECASTS.labels(projected_level=projected_level).inc()
        WORKLOAD_FORECAST_LAST_RUN.set(time.time())
    except Exception:  # pragma: no cover
        pass
