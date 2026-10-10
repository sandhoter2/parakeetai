"""
Data migration: assign all InterviewSession records that have owner=NULL
to the first superuser (admin). Safe to run repeatedly — skips if no
orphaned sessions exist or no superuser is found.
"""

from django.db import migrations


def backfill_owners(apps, schema_editor):
    InterviewSession = apps.get_model("interview", "InterviewSession")
    User = apps.get_model("auth", "User")

    orphaned = InterviewSession.objects.filter(owner__isnull=True)
    if not orphaned.exists():
        return

    # Prefer the first superuser, fall back to any user
    admin = User.objects.filter(is_superuser=True).order_by("id").first()
    if not admin:
        admin = User.objects.order_by("id").first()
    if not admin:
        return  # No users yet — nothing to assign

    orphaned.update(owner=admin)


def reverse_backfill(apps, schema_editor):
    pass  # Intentionally irreversible — don't null out owners on rollback


class Migration(migrations.Migration):

    dependencies = [
        ("interview", "0012_add_prep_notes_to_session"),
    ]

    operations = [
        migrations.RunPython(backfill_owners, reverse_backfill),
    ]
