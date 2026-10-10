import uuid
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


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

    PLAN_FREE = "free"
    PLAN_PRO = "pro"
    PLAN_TEAM = "team"
    PLAN_CHOICES = [
        (PLAN_FREE, "Free"),
        (PLAN_PRO, "Pro"),
        (PLAN_TEAM, "Team"),
    ]
    FREE_SESSION_LIMIT = 5

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="engineer", blank=True)
    company = models.CharField(max_length=200, blank=True)
    background = models.TextField(blank=True, help_text="Resume / skills summary used as default context.")
    ext_token = models.CharField(max_length=64, unique=True, blank=True, default="",
                                 help_text="Static token used by the Electron overlay to authenticate API calls.")
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default=PLAN_FREE)
    stripe_customer_id = models.CharField(max_length=64, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_free(self):
        return self.plan == self.PLAN_FREE

    @property
    def session_limit(self):
        if self.plan == self.PLAN_FREE:
            return self.FREE_SESSION_LIMIT
        return None  # unlimited for paid plans

    def save(self, *args, **kwargs):
        if not self.ext_token:
            self.ext_token = uuid.uuid4().hex + uuid.uuid4().hex
        super().save(*args, **kwargs)

    def regenerate_token(self):
        self.ext_token = uuid.uuid4().hex + uuid.uuid4().hex  # 64-char hex
        self.save(update_fields=["ext_token"])

    def __str__(self):
        return f"{self.user.username} — {self.get_role_display()}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


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
    prep_notes = models.TextField(
        blank=True,
        help_text="Interview preparation tips, talking points, and STAR examples.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} @ {self.company}" if self.company else self.title


class TranscriptEntry(models.Model):
    TYPE_MIC = "microphone"
    TYPE_SYSTEM = "system"
    TYPE_NOTE = "note"
    TYPE_CHOICES = [
        (TYPE_MIC, "Microphone"),
        (TYPE_SYSTEM, "System Audio"),
        (TYPE_NOTE, "Note"),
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


class DbSyncLog(models.Model):
    DIRECTION_BACKUP = "backup"
    DIRECTION_RESTORE = "restore"
    DIRECTION_CHOICES = [("backup", "SQLite → MySQL"), ("restore", "MySQL → SQLite")]

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [("running", "Running"), ("success", "Success"), ("error", "Error")]

    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="running")
    records_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    triggered_by = models.CharField(max_length=50, blank=True)  # 'startup', 'session_end', 'manual'
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.direction} {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


class PromptTemplate(models.Model):
    TYPE_AI_HELP = "ai_help"
    TYPE_MEETING_AI = "meeting_ai"
    TYPE_CONVERSATION = "conversation"
    TYPE_CHOICES = [("ai_help", "AI Help"), ("meeting_ai", "Meeting AI"), ("conversation", "Conversation")]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="prompt_templates")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    prompt = models.TextField()
    icon = models.CharField(max_length=10, default="✨")
    template_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="ai_help")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.template_type})"
