import uuid
from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ("architect", "Architect"),
        ("engineer", "Software Engineer"),
        ("pm", "Product Manager"),
        ("data", "Data Scientist"),
        ("ml", "ML Engineer"),
        ("designer", "UX Designer"),
        ("other", "Other"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="engineer", blank=True)
    company = models.CharField(max_length=200, blank=True)
    background = models.TextField(blank=True, help_text="Resume / skills summary used as default context.")
    ext_token = models.CharField(max_length=64, unique=True, blank=True, default="",
                                 help_text="Static token used by the Electron overlay to authenticate API calls.")
    created_at = models.DateTimeField(auto_now_add=True)

    def regenerate_token(self):
        self.ext_token = uuid.uuid4().hex + uuid.uuid4().hex  # 64-char hex
        self.save(update_fields=["ext_token"])

    def __str__(self):
        return f"{self.user.username} — {self.get_role_display()}"


class InterviewSession(models.Model):
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sessions", null=True, blank=True
    )
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_ENDED = "ended"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ENDED, "Ended"),
    ]

    SESSION_TYPE_INTERVIEW = "interview"
    SESSION_TYPE_MEETING = "meeting"
    SESSION_TYPE_CHOICES = [
        (SESSION_TYPE_INTERVIEW, "Interview"),
        (SESSION_TYPE_MEETING, "Teams Meeting"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200, blank=True)
    job_description = models.TextField(blank=True)
    extra_context = models.TextField(
        blank=True,
        help_text="Paste your resume, skills, and background here.",
    )
    language = models.CharField(max_length=10, default="en-US")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    session_type = models.CharField(
        max_length=20, choices=SESSION_TYPE_CHOICES, default=SESSION_TYPE_INTERVIEW
    )
    meeting_agenda = models.TextField(blank=True, help_text="Agenda items for the meeting.")
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} @ {self.company}" if self.company else self.title


class TranscriptEntry(models.Model):
    TYPE_MIC = "microphone"
    TYPE_SYSTEM = "system"
    TYPE_CHOICES = [
        (TYPE_MIC, "Microphone"),
        (TYPE_SYSTEM, "System Audio"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        InterviewSession, on_delete=models.CASCADE, related_name="transcripts"
    )
    content = models.TextField()
    speaker_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_MIC)
    speaker_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.speaker_type}] {self.content[:60]}"


class MeetingParticipant(models.Model):
    COLORS = [
        "#6c63ff", "#3b82f6", "#10b981", "#f59e0b",
        "#ec4899", "#06b6d4", "#f97316", "#8b5cf6",
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        InterviewSession, on_delete=models.CASCADE, related_name="participants"
    )
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=7, default="#6c63ff")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = [("session", "name")]

    def __str__(self):
        return f"{self.name} ({self.session.title})"


class AIMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        InterviewSession, on_delete=models.CASCADE, related_name="ai_messages"
    )
    trigger_text = models.TextField(blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"AI: {self.content[:60]}"
