from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    RebalancingView,
    ScoreTrendView,
    AlertViewSet,
    ComputeScoreView,
    ScoreListView,
    TaskViewSet,
    TeamOverviewView,
    WorkdaySignalListCreateView,
)

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="workload-task")
router.register("alerts", AlertViewSet, basename="workload-alert")

urlpatterns = [
    path("signals/", WorkdaySignalListCreateView.as_view(), name="workload-signals"),
    path("scores/", ScoreListView.as_view(), name="workload-scores"),
    path("scores/compute/", ComputeScoreView.as_view(), name="workload-compute"),
    path("scores/trend/", ScoreTrendView.as_view(), name="workload-trend"),
    path("rebalancing/", RebalancingView.as_view(), name="workload-rebalancing"),
    path("team-overview/", TeamOverviewView.as_view(), name="workload-team-overview"),
    path("", include(router.urls)),
]
