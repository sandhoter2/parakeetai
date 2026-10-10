"""Seed initial Jira-style tasks into the Task board."""
from django.core.management.base import BaseCommand
from interview.models import Task


INITIAL_TASKS = [
    # TODO
    dict(title="Add Stripe webhook for subscription updates", description="Handle customer.subscription.updated and customer.subscription.deleted events to sync plan field on UserProfile.", status="todo", priority="high", category="feature", order=1),
    dict(title="Implement session sharing via public link", description="Allow users to generate a read-only shareable link for a session detail page.", status="todo", priority="medium", category="feature", order=2),
    dict(title="Add email notifications for session end", description="Send a summary email when a session ends with transcript count and AI answer highlights.", status="todo", priority="low", category="feature", order=3),
    dict(title="Mobile-responsive layout fixes", description="Home page and session detail are not fully responsive below 480px — cards overflow on small screens.", status="todo", priority="medium", category="improvement", order=4),
    dict(title="Rate limiting on AI answer API", description="Add per-user rate limiting on /api/session/<id>/ai/ to prevent abuse on Free plan.", status="todo", priority="high", category="security", order=5),

    # IN PROGRESS
    dict(title="Jira-style task board in admin", description="Kanban board at /admin/interview/task/board/ with TODO / In Progress / Done columns.", status="in_progress", priority="high", category="feature", order=1),
    dict(title="Upgrade to Claude claude-sonnet-4-6 for AI answers", description="Switch AI answer generation from GPT-4o to Claude claude-sonnet-4-6. Update prompt format and streaming handler.", status="in_progress", priority="high", category="improvement", order=2),

    # IN REVIEW
    dict(title="Fix null-owner session Q() filter", description="Sessions with null owner were not showing. Added Q(owner=user)|Q(owner__isnull=True) fallback.", status="in_review", priority="critical", category="bug", order=1),
    dict(title="Session export TXT/MD", description="Export buttons on detail page download properly formatted .txt and .md files.", status="in_review", priority="medium", category="feature", order=2),

    # DONE
    dict(title="Deploy to Render with MySQL", description="Dockerized app deployed to Render; MySQL at srv2036.hstgr.io connected via env vars.", status="done", priority="critical", category="infra", order=1),
    dict(title="Chrome Extension overlay integration", description="Electron overlay authenticates via ext_token header; sessions linked to user profiles.", status="done", priority="high", category="feature", order=2),
    dict(title="User authentication (login/signup/logout)", description="Custom login/signup views at /login/ and /signup/ with session management.", status="done", priority="high", category="feature", order=3),
    dict(title="Prompt templates with seed command", description="UserProfile gets default prompt templates on signup via seed_templates management command.", status="done", priority="medium", category="feature", order=4),
    dict(title="superuser creation in build.sh before migrate", description="Moved createsuperuser --noinput before migrate so migration 0013 backfill finds the admin user.", status="done", priority="high", category="infra", order=5),

    # BLOCKED
    dict(title="Stripe payment integration (live keys)", description="Waiting on Stripe live API keys from account owner. Test mode wired; production keys pending.", status="blocked", priority="critical", category="feature", order=1),
    dict(title="Apple App Store submission for iOS companion app", description="Blocked on Apple Developer account enrollment ($99/yr). App built; cannot submit without account.", status="blocked", priority="medium", category="infra", order=2),

    # NEW
    dict(title="Add dark mode toggle to user settings page", description="Allow users to switch between light and dark themes from their profile settings. Persist preference in UserProfile model.", status="todo", priority="medium", category="improvement", order=6),
]


class Command(BaseCommand):
    help = "Seed initial tasks into the Jira board (skips if tasks already exist)"

    def handle(self, *args, **options):
        if Task.objects.exists():
            self.stdout.write("    Tasks already seeded — skipping.")
            return
        for t in INITIAL_TASKS:
            Task.objects.create(**t)
        self.stdout.write(self.style.SUCCESS(f"    Seeded {len(INITIAL_TASKS)} tasks."))
