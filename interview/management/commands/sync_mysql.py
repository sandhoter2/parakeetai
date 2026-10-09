"""
Sync SQLite ↔ MySQL backup database.

Usage:
    python manage.py sync_mysql backup    # SQLite → MySQL
    python manage.py sync_mysql restore   # MySQL → SQLite
"""
from django.core.management.base import BaseCommand, CommandError
from interview.db_sync import backup_to_mysql, restore_from_mysql


class Command(BaseCommand):
    help = "Sync data between SQLite (working DB) and MySQL (persistent backup)"

    def add_arguments(self, parser):
        parser.add_argument(
            "direction",
            choices=["backup", "restore"],
            help="'backup' = SQLite→MySQL, 'restore' = MySQL→SQLite",
        )

    def handle(self, *args, **options):
        direction = options["direction"]
        if direction == "backup":
            count, err = backup_to_mysql(triggered_by="manual")
            if err:
                raise CommandError(f"Backup failed: {err}")
            self.stdout.write(self.style.SUCCESS(f"Backup complete: {count} records → MySQL"))
        else:
            count, err = restore_from_mysql(triggered_by="manual")
            if err:
                raise CommandError(f"Restore failed: {err}")
            self.stdout.write(self.style.SUCCESS(f"Restore complete: {count} records ← MySQL"))
