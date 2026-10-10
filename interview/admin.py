import datetime

from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import AIMessage, InterviewSession, Task, TranscriptEntry, UserProfile


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


COLUMNS = [
    {"key": "todo",        "label": "To Do",       "color": "#3b82f6", "icon": "📋", "empty_icon": "📭"},
    {"key": "in_progress", "label": "In Progress",  "color": "#f59e0b", "icon": "⚡", "empty_icon": "💤"},
    {"key": "in_review",   "label": "In Review",    "color": "#8b5cf6", "icon": "🔍", "empty_icon": "👁"},
    {"key": "done",        "label": "Done",         "color": "#10b981", "icon": "✅", "empty_icon": "🎉"},
    {"key": "blocked",     "label": "Blocked",      "color": "#ef4444", "icon": "🚫", "empty_icon": "✨"},
]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "status_badge", "priority_badge", "category_tag", "assignee", "due_date", "created_at")
    list_filter = ("status", "priority", "category", "assignee")
    search_fields = ("title", "description")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("order", "-created_at")
    list_per_page = 50
    date_hierarchy = "created_at"
    change_list_template = "admin/interview/task_change_list.html"

    fieldsets = (
        ("Task", {"fields": ("id", "title", "description")}),
        ("Classification", {"fields": ("status", "priority", "category")}),
        ("Assignment", {"fields": ("assignee", "created_by", "due_date", "order")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [path("board/", self.admin_site.admin_view(self.board_view), name="task_board")]
        return custom + urls

    def board_view(self, request):
        priority_filter = request.GET.get("priority")
        cat_filter = request.GET.get("cat")

        qs = Task.objects.select_related("assignee", "created_by").all()
        if priority_filter:
            qs = qs.filter(priority=priority_filter)
        if cat_filter:
            qs = qs.filter(category=cat_filter)

        today = datetime.date.today()
        tasks_by_status = {c["key"]: [] for c in COLUMNS}
        for task in qs:
            task.is_overdue = bool(task.due_date and task.due_date < today and task.status != Task.STATUS_DONE)
            if task.status in tasks_by_status:
                tasks_by_status[task.status].append(task)

        columns = [{**c, "tasks": tasks_by_status[c["key"]]} for c in COLUMNS]

        counts = {c["key"]: Task.objects.filter(status=c["key"]).count() for c in COLUMNS}
        cat_counts = {cat: Task.objects.filter(category=cat).count()
                      for cat, _ in Task.CATEGORY_CHOICES}

        ctx = {
            **self.admin_site.each_context(request),
            "title": "Task Board",
            "columns": columns,
            "counts": counts,
            "category_counts": cat_counts,
            "total_tasks": Task.objects.count(),
        }
        return render(request, "admin/interview/task_board.html", ctx)

    def status_badge(self, obj):
        colors = {
            "todo": "#3b82f6", "in_progress": "#f59e0b",
            "in_review": "#8b5cf6", "done": "#10b981", "blocked": "#ef4444",
        }
        icons = {"todo": "📋", "in_progress": "⚡", "in_review": "🔍", "done": "✅", "blocked": "🚫"}
        c = colors.get(obj.status, "#94a3b8")
        return format_html(
            '<span style="background:{}22;color:{};padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700">{} {}</span>',
            c, c, icons.get(obj.status, ""), obj.get_status_display()
        )
    status_badge.short_description = "Status"

    def priority_badge(self, obj):
        colors = {"low": "#4ade80", "medium": "#fbbf24", "high": "#f97316", "critical": "#ef4444"}
        c = colors.get(obj.priority, "#94a3b8")
        return format_html(
            '<span style="color:{};font-weight:700;font-size:11px">● {}</span>',
            c, obj.get_priority_display()
        )
    priority_badge.short_description = "Priority"

    def category_tag(self, obj):
        colors = {
            "feature": "#60a5fa", "bug": "#f87171", "improvement": "#4ade80",
            "infra": "#fbbf24", "docs": "#a78bfa", "security": "#f472b6",
        }
        c = colors.get(obj.category, "#94a3b8")
        return format_html(
            '<span style="background:{}20;color:{};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">{}</span>',
            c, c, obj.get_category_display()
        )
    category_tag.short_description = "Category"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["board_url"] = "../board/"
        return super().changelist_view(request, extra_context=extra_context)


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
