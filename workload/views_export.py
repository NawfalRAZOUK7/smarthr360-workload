"""CSV export of the team workload report (managers / HR).

Reuses the same per-employee aggregation that powers the team-overview screen,
and streams it as a downloadable CSV so managers can share or archive a
snapshot of workload and burnout levels.
"""

import csv
from datetime import date

from django.http import HttpResponse
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from smarthr360_jwt_auth.access import has_manager_access

from .models import Task
from .services import scoring


class WorkloadExportView(APIView):
    """GET /api/workload/export/?user_ids=1,2,3 — team workload as CSV."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_manager_access(request.user):
            raise PermissionDenied("Managers/HR only.")

        raw = request.query_params.get("user_ids", "")
        try:
            user_ids = [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            user_ids = []
        if not user_ids:
            user_ids = list(Task.objects.values_list("user_id", flat=True).distinct())

        rows = scoring.team_overview(user_ids)

        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = (
            f'attachment; filename="workload_report_{date.today().isoformat()}.csv"'
        )
        writer = csv.writer(resp)
        writer.writerow(["user_id", "score", "level", "open_hours", "computed_at"])
        for r in rows:
            writer.writerow(
                [
                    r.get("user_id"),
                    r.get("score") if r.get("score") is not None else "",
                    r.get("level") or "",
                    r.get("open_hours") if r.get("open_hours") is not None else "",
                    r.get("computed_at") or "",
                ]
            )
        return resp
