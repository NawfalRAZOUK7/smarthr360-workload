"""Workload APIs (Module 1).

Scoping rules:
- employees: their own tasks/signals/scores/alerts
- managers/HR/admin: any user via ?user_id= (managers are trusted at
  the role level here; fine-grained team membership lives in core-hr)
"""

from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from smarthr360_jwt_auth.access import has_manager_access

from .models import Task, WorkdaySignal, WorkloadAlert, WorkloadScore
from .serializers import (
    TaskSerializer,
    WorkdaySignalSerializer,
    WorkloadAlertSerializer,
    WorkloadScoreSerializer,
)
from .services import scoring


def _target_user_id(request) -> int:
    """The user whose data is addressed: self, or ?user_id= for managers."""
    requested = request.query_params.get("user_id") or request.data.get("user_id")
    if requested and int(requested) != int(request.user.id):
        if not has_manager_access(request.user):
            raise PermissionDenied("Only managers/HR may address other users.")
        return int(requested)
    return int(request.user.id)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if has_manager_access(self.request.user):
            requested = self.request.query_params.get("user_id")
            qs = Task.objects.all()
            return qs.filter(user_id=requested) if requested else qs
        return Task.objects.filter(user_id=self.request.user.id)

    def perform_create(self, serializer):
        user_id = serializer.validated_data.get("user_id") or self.request.user.id
        if int(user_id) != int(self.request.user.id) and not has_manager_access(
            self.request.user
        ):
            raise PermissionDenied("Only managers/HR may assign tasks to others.")
        serializer.save(
            user_id=user_id, created_by_user_id=self.request.user.id
        )


class WorkdaySignalListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkdaySignalSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WorkdaySignal.objects.filter(user_id=_target_user_id(self.request))

    def perform_create(self, serializer):
        # Signals are strictly self-reported.
        serializer.save(user_id=self.request.user.id)


class ComputeScoreView(APIView):
    """POST /scores/compute/ — run the scoring engine now.

    On HIGH/CRITICAL alerts, pushes a burnout signal to the retention
    service (best-effort, token pass-through) so the retention chatbot
    can reach out proactively — cross-service signal wiring.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = _target_user_id(request)
        result = scoring.compute_score(user_id)

        retention_notified = False
        if result.alert is not None:
            from .clients import RetentionClient

            retention_notified = RetentionClient(request.auth).notify_burnout(
                user_id=user_id,
                intensity=int(min(100, result.score)),
                message=result.alert.message,
            )

        payload = {
            "user_id": user_id,
            "score": result.score,
            "level": result.level,
            "components": result.components,
            "alert": WorkloadAlertSerializer(result.alert).data
            if result.alert
            else None,
            "retention_notified": retention_notified,
        }
        return Response(payload, status=status.HTTP_201_CREATED)


class ScoreListView(generics.ListAPIView):
    serializer_class = WorkloadScoreSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WorkloadScore.objects.filter(user_id=_target_user_id(self.request))


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WorkloadAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if has_manager_access(self.request.user):
            requested = self.request.query_params.get("user_id")
            qs = WorkloadAlert.objects.all()
            return qs.filter(user_id=requested) if requested else qs
        return WorkloadAlert.objects.filter(user_id=self.request.user.id)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        if not has_manager_access(request.user):
            raise PermissionDenied("Only managers/HR may acknowledge alerts.")
        alert = self.get_object()
        alert.acknowledged = True
        alert.acknowledged_by_user_id = request.user.id
        alert.save(update_fields=["acknowledged", "acknowledged_by_user_id"])
        return Response(WorkloadAlertSerializer(alert).data)


class TeamOverviewView(APIView):
    """GET /team-overview/?user_ids=1,2,3 — latest score per employee."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_manager_access(request.user):
            raise PermissionDenied("Managers/HR only.")
        raw = request.query_params.get("user_ids", "")
        try:
            user_ids = [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            return Response(
                {"detail": "user_ids must be a comma-separated list of ids."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user_ids:
            user_ids = list(
                Task.objects.values_list("user_id", flat=True).distinct()
            )
        return Response({"team": scoring.team_overview(user_ids)})
