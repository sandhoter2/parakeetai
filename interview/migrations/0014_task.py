import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("interview", "0013_backfill_session_owners"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Task",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(
                    choices=[
                        ("todo", "To Do"),
                        ("in_progress", "In Progress"),
                        ("in_review", "In Review"),
                        ("done", "Done"),
                        ("blocked", "Blocked"),
                    ],
                    default="todo",
                    max_length=20,
                )),
                ("priority", models.CharField(
                    choices=[
                        ("low", "Low"),
                        ("medium", "Medium"),
                        ("high", "High"),
                        ("critical", "Critical"),
                    ],
                    default="medium",
                    max_length=20,
                )),
                ("category", models.CharField(
                    choices=[
                        ("feature", "Feature"),
                        ("bug", "Bug"),
                        ("improvement", "Improvement"),
                        ("infra", "Infrastructure"),
                        ("docs", "Documentation"),
                        ("security", "Security"),
                    ],
                    default="feature",
                    max_length=20,
                )),
                ("due_date", models.DateField(blank=True, null=True)),
                ("order", models.PositiveIntegerField(default=0, help_text="Sort order within the column.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assignee", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="assigned_tasks",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_tasks",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["order", "-created_at"]},
        ),
    ]
