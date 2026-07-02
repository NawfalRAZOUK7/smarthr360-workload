from django.contrib import admin

from .models import Task, WorkdaySignal, WorkloadAlert, WorkloadScore


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


admin.site.register(WorkdaySignal)
