"""SCD Type 2 timeline of workload level transitions (Phase 1).

Uses the shared SCD2 base fields (smarthr360-integration) plus the workload-
specific owner and level columns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workload", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkloadLevelHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("date_debut", models.DateTimeField(db_index=True)),
                ("date_fin", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("is_current", models.BooleanField(default=True)),
                ("change_reason", models.CharField(blank=True, max_length=255)),
                ("changed_by_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("source_system", models.CharField(blank=True, max_length=32)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("employee_user_id", models.PositiveBigIntegerField(db_index=True)),
                ("level", models.CharField(max_length=20)),
            ],
            options={
                "ordering": ["employee_user_id", "-date_debut"],
            },
        ),
        migrations.AddIndex(
            model_name="workloadlevelhistory",
            index=models.Index(
                fields=["employee_user_id", "is_current"],
                name="wl_levelhist_emp_curr_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="workloadlevelhistory",
            constraint=models.UniqueConstraint(
                condition=models.Q(("date_fin__isnull", True)),
                fields=("employee_user_id",),
                name="uniq_open_workload_level_per_employee",
            ),
        ),
        migrations.AddConstraint(
            model_name="workloadlevelhistory",
            constraint=models.UniqueConstraint(
                fields=("employee_user_id", "version"),
                name="uniq_workload_level_version",
            ),
        ),
    ]
