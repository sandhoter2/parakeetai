"""
Management command: assign_session_owners

Assigns all InterviewSession records with owner=NULL to a specified user.
Run after deploying the owner-enforcement fix to backfill legacy sessions.

Usage:
    python manage.py assign_session_owners --username <username>
    python manage.py assign_session_owners --list-users
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from interview.models import InterviewSession


class Command(BaseCommand):
    help = "Assign unowned (owner=NULL) sessions to a specific user."

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, help="Username to assign orphaned sessions to")
        parser.add_argument("--list-users", action="store_true", help="List all users and orphaned session counts")

    def handle(self, *args, **options):
        orphaned = InterviewSession.objects.filter(owner__isnull=True)
        orphaned_count = orphaned.count()

        if options["list_users"]:
            self.stdout.write(f"Orphaned sessions (owner=NULL): {orphaned_count}\n")
            self.stdout.write("Users in database:")
            for u in User.objects.all().order_by("username"):
                owned = InterviewSession.objects.filter(owner=u).count()
                self.stdout.write(f"  {u.username} (id={u.id}) — {owned} sessions")
            return

        if not options["username"]:
            raise CommandError("Provide --username or --list-users")

        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"User '{options['username']}' not found. Use --list-users to see available users.")

        if orphaned_count == 0:
            self.stdout.write(self.style.SUCCESS("No orphaned sessions found. Nothing to do."))
            return

        updated = orphaned.update(owner=user)
        self.stdout.write(
            self.style.SUCCESS(f"Assigned {updated} orphaned sessions to user '{user.username}' (id={user.id})")
        )
