"""Bulk import of tasks — feed the burnout model with real workload data.

The burnout forecast is only as good as the task/hours data behind it. This
lets a manager/HR paste or upload a batch of real assignments in one call
(instead of one-by-one), so the model reflects reality rather than seed data.
Reuses the existing Task model — no schema change.
"""

from rest_framework import status as http_status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from smarthr360_jwt_auth.access import has_manager_access

from .models import Task

_VALID_STATUS = {s.value for s in Task.Status}


class WorkloadTaskImportView(APIView):
    """POST /api/workload/tasks/import/ {tasks: [{user_id, title, ...}]}.

    Each row: user_id + title required; estimated_hours (default 1),
    complexity 1-5 (default 2), status (default TODO), deadline (optional).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not has_manager_access(request.user):
            raise PermissionDenied("Managers/HR only.")

        rows = request.data.get("tasks")
        if not isinstance(rows, list) or not rows:
            return Response(
                {"detail": "tasks must be a non-empty list."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if len(rows) > 500:
            return Response(
                {"detail": "import at most 500 tasks at once."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        to_create = []
        errors = []
        for i, row in enumerate(rows):
            try:
                uid = int(row.get("user_id"))
                title = str(row.get("title") or "").strip()
                if not title:
                    raise ValueError("title is required")
                hours = float(row.get("estimated_hours") or 1.0)
                complexity = int(row.get("complexity") or 2)
                complexity = max(1, min(complexity, 5))
                st = row.get("status") or Task.Status.TODO
                if st not in _VALID_STATUS:
                    st = Task.Status.TODO
                to_create.append(
                    Task(
                        user_id=uid,
                        title=title[:255],
                        estimated_hours=hours,
                        complexity=complexity,
                        status=st,
                        deadline=row.get("deadline") or None,
                        created_by_user_id=request.user.id,
                    )
                )
            except (TypeError, ValueError) as exc:
                errors.append({"index": i, "error": str(exc)})

        created = Task.objects.bulk_create(to_create)
        return Response(
            {"created": len(created), "errors": errors},
            status=http_status.HTTP_201_CREATED if created else http_status.HTTP_400_BAD_REQUEST,
        )
