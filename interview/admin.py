from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import AIMessage, InterviewSession, TranscriptEntry, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "role", "company", "created_at")
    search_fields = ("user__username", "user__email", "display_name", "company")
    list_filter = ("role",)
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Account", {"fields": ("user", "display_name")}),
        ("Professional", {"fields": ("role", "company", "background")}),
        ("Meta", {"fields": ("created_at",)}),
    )


class TranscriptEntryInline(admin.TabularInline):
    model = TranscriptEntry
    extra = 0
    readonly_fields = ("id", "speaker_type", "content", "created_at")
    fields = ("speaker_type", "content", "created_at")
    can_delete = True
    max_num = 0
    show_change_link = False


class AIMessageInline(admin.TabularInline):
    model = AIMessage
    extra = 0
    readonly_fields = ("id", "trigger_text", "content_preview", "created_at")
    fields = ("trigger_text", "content_preview", "created_at")
    can_delete = True
    max_num = 0

    def content_preview(self, obj):
        return obj.content[:120] + "…" if len(obj.content) > 120 else obj.content
    content_preview.short_description = "AI Response"


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = (
        "title", "company", "status_badge", "transcript_count",
        "ai_count", "language", "created_at_display",
    )
    list_filter = ("status", "language", "created_at")
    search_fields = ("title", "company", "job_description")
    readonly_fields = ("id", "created_at", "ended_at")
    inlines = [TranscriptEntryInline, AIMessageInline]
    ordering = ("-created_at",)
    list_per_page = 25

    fieldsets = (
        ("Session Info", {
            "fields": ("id", "title", "company", "language", "status"),
        }),
        ("Context", {
            "fields": ("job_description", "extra_context"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "ended_at"),
        }),
    )

    def status_badge(self, obj):
        colors = {"active": "#34d399", "ended": "#64748b", "pending": "#f59e0b"}
        c = colors.get(obj.status, "#94a3b8")
        return format_html(
            '<span style="background:{}22;color:{};padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700">{}</span>',
            c, c, obj.status.upper()
        )
    status_badge.short_description = "Status"

    def transcript_count(self, obj):
        n = obj.transcripts.count()
        return format_html('<span style="color:#94a3b8">🎙 {}</span>', n)
    transcript_count.short_description = "Transcripts"

    def ai_count(self, obj):
        n = obj.ai_messages.count()
        return format_html('<span style="color:#a78bfa">✨ {}</span>', n)
    ai_count.short_description = "AI Msgs"

    def created_at_display(self, obj):
        return localtime(obj.created_at).strftime("%b %d, %Y %I:%M %p")
    created_at_display.short_description = "Created"


@admin.register(TranscriptEntry)
class TranscriptEntryAdmin(admin.ModelAdmin):
    list_display = ("session_link", "speaker_type", "content_preview", "created_at")
    list_filter = ("speaker_type", "created_at")
    search_fields = ("content", "session__title")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
    list_per_page = 50

    def session_link(self, obj):
        return format_html(
            '<a href="/admin/interview/interviewsession/{}/change/">{}</a>',
            obj.session.id, obj.session.title[:40]
        )
    session_link.short_description = "Session"

    def content_preview(self, obj):
        return obj.content[:80] + "…" if len(obj.content) > 80 else obj.content
    content_preview.short_description = "Content"


@admin.register(AIMessage)
class AIMessageAdmin(admin.ModelAdmin):
    list_display = ("session_link", "trigger_preview", "content_preview", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "trigger_text", "session__title")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
    list_per_page = 50

    def session_link(self, obj):
        return format_html(
            '<a href="/admin/interview/interviewsession/{}/change/">{}</a>',
            obj.session.id, obj.session.title[:40]
        )
    session_link.short_description = "Session"

    def trigger_preview(self, obj):
        return obj.trigger_text[:60] + "…" if len(obj.trigger_text) > 60 else obj.trigger_text
    trigger_preview.short_description = "Trigger"

    def content_preview(self, obj):
        return obj.content[:80] + "…" if len(obj.content) > 80 else obj.content
    content_preview.short_description = "AI Response"
