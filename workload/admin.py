from django.contrib import admin

from .models import (
    Task,
    WorkdaySignal,
    WorkloadAlert,
    WorkloadLevelHistory,
    WorkloadScore,
)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "user_id", "status", "estimated_hours", "complexity", "deadline")
    list_filter = ("status", "is_unplanned")


@admin.register(WorkloadScore)
class WorkloadScoreAdmin(admin.ModelAdmin):
    list_display = ("user_id", "score", "level", "computed_at")
    list_filter = ("level",)


@admin.register(WorkloadAlert)
class WorkloadAlertAdmin(admin.ModelAdmin):
    list_display = ("user_id", "level", "acknowledged", "created_at")
    list_filter = ("level", "acknowledged")


@admin.register(WorkloadLevelHistory)
class WorkloadLevelHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "employee_user_id",
        "level",
        "version",
        "date_debut",
        "date_fin",
        "is_current",
    )
    list_filter = ("level", "is_current")
    search_fields = ("employee_user_id",)
    date_hierarchy = "date_debut"


admin.site.register(WorkdaySignal)
