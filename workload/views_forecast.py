"""Burnout forecast endpoints (Phase 1 feature).

    GET /api/workload/forecast/?user_id=&horizon_days=14   single employee
    GET /api/workload/forecast/team/?horizon_days=14        manager's team

The team view reads the manager's direct reports from core-hr via the shared
CoreHRClient — the team roster is *owned* by core-hr, never duplicated here.
"""

from __future__ import annotations

import os

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from smarthr360_integration.api import bad_request, forbidden
from smarthr360_jwt_auth.access import has_manager_access

from .metrics import record_forecast, set_burnout_risk_count
from .models import WorkloadScore
from .services.forecast import DEFAULT_HORIZON_DAYS, forecast_burnout
from .views import _target_user_id


def _horizon(request):
    raw = request.query_params.get("horizon_days")
    if raw is None:
        return DEFAULT_HORIZON_DAYS, None
    if not raw.isdigit() or not (1 <= int(raw) <= 90):
        return None, bad_request("invalid_parameter", "horizon_days must be 1..90.")
    return int(raw), None


class BurnoutForecastView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = _target_user_id(request)
        horizon, err = _horizon(request)
        if err:
            return err
        fc = forecast_burnout(user_id, horizon_days=horizon)
        record_forecast(fc.projected_level or "NONE")
        from rest_framework.response import Response

        return Response({"data": fc.as_dict(), "meta": {"success": True}})


class TeamBurnoutForecastView(APIView):
    """Forecast for every member of the manager's team (roster from core-hr)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_manager_access(request.user):
            return forbidden("Manager, HR or Admin role required.")
        horizon, err = _horizon(request)
        if err:
            return err

        user_ids = self._team_user_ids(request)

        forecasts = []
        risk_count = 0
        for uid in user_ids:
            fc = forecast_burnout(uid, horizon_days=horizon)
            record_forecast(fc.projected_level or "NONE")
            if fc.projected_level in ("HIGH", "BURNOUT_RISK"):
                risk_count += 1
            forecasts.append(fc.as_dict())

        # Update the burnout-risk gauge from the *current* latest scores.
        set_burnout_risk_count(
            WorkloadScore.objects.filter(
                user_id__in=user_ids, level__in=["HIGH", "BURNOUT_RISK"]
            ).count()
        )

        forecasts.sort(key=lambda f: (f["projected_score"] or -1), reverse=True)
        from rest_framework.response import Response

        return Response(
            {
                "data": {
                    "horizon_days": horizon,
                    "team_size": len(user_ids),
                    "projected_at_risk": risk_count,
                    "forecasts": forecasts,
                },
                "meta": {"success": True},
            }
        )

    def _team_user_ids(self, request) -> list[int]:
        """Direct reports from core-hr (owned there); fallback to the manager."""
        try:
            from smarthr360_integration.clients import CoreHRClient

            base = os.environ.get("CORE_HR_API_URL", "http://core-hr:8000")
            client = CoreHRClient(base, token=request.auth)
            chart = client.org_chart()
            me = int(request.user.id)
            return _reports_of(chart, me) or [me]
        except Exception:
            # core-hr outage must not break the forecast — degrade to self.
            return [int(request.user.id)]


def _reports_of(org_chart: dict, manager_user_id: int) -> list[int]:
    """Extract the direct reports' user_ids for a manager from the org chart."""
    found: list[int] = []

    def walk(node):
        if node.get("user_id") == manager_user_id:
            for child in node.get("reports", []):
                if child.get("user_id"):
                    found.append(int(child["user_id"]))
            return True
        return any(walk(c) for c in node.get("reports", []))

    for root in org_chart.get("roots", []):
        if walk(root):
            break
    return found
