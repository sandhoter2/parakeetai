from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("interview", "0003_userprofile_ext_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="interviewsession",
            name="session_type",
            field=models.CharField(
                choices=[("interview", "Interview"), ("meeting", "Teams Meeting")],
                default="interview",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="interviewsession",
            name="meeting_agenda",
            field=models.TextField(
                blank=True,
                help_text="Agenda items for the meeting.",
            ),
        ),
        migrations.AddField(
            model_name="transcriptentry",
            name="speaker_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.CreateModel(
            name="MeetingParticipant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
                ("role", models.CharField(blank=True, max_length=100)),
                ("color", models.CharField(default="#6c63ff", max_length=7)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="participants",
                        to="interview.interviewsession",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "unique_together": {("session", "name")},
            },
        ),
    ]
