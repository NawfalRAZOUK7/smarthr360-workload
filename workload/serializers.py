from rest_framework import serializers

from .models import Task, WorkdaySignal, WorkloadAlert, WorkloadScore


class TaskSerializer(serializers.ModelSerializer):
    # Optional on create: defaults to the requester (view enforces rules)
    user_id = serializers.IntegerField(required=False)

    class Meta:
        model = Task
        fields = [
            "id", "user_id", "title", "description", "status",
            "estimated_hours", "complexity", "deadline", "is_unplanned",
            "reference", "created_by_user_id", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by_user_id", "created_at", "updated_at"]

    def validate_complexity(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("complexity must be between 1 and 5.")
        return value


class WorkdaySignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkdaySignal
        fields = [
            "id", "user_id", "date", "meetings_count",
            "interruptions_count", "stress_level", "comment", "created_at",
        ]
        read_only_fields = ["user_id", "created_at"]

    def validate_stress_level(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("stress_level must be between 1 and 5.")
        return value


class WorkloadScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkloadScore
        fields = ["id", "user_id", "score", "level", "components", "computed_at"]


class WorkloadAlertSerializer(serializers.ModelSerializer):
    score_value = serializers.FloatField(source="score.score", read_only=True)

    class Meta:
        model = WorkloadAlert
        fields = [
            "id", "user_id", "level", "message", "recommendations",
            "score_value", "acknowledged", "acknowledged_by_user_id", "created_at",
        ]
        read_only_fields = [
            "user_id", "level", "message", "recommendations",
            "score_value", "created_at",
        ]
