"""
Export app data to fixtures/db_backup.json.
Run before a deployment or commit to preserve data across Render redeploys.

Usage:
    python manage.py export_db
    python manage.py export_db --output fixtures/snapshot_2026.json
"""
import json
import sys
from pathlib import Path

from django.core import serializers
from django.core.management.base import BaseCommand
from django.apps import apps


EXPORT_APPS = ["interview", "auth"]
EXCLUDE_MODELS = {"auth.permission", "contenttypes.contenttype"}

DEFAULT_OUTPUT = Path("fixtures/db_backup.json")


class Command(BaseCommand):
    help = "Export interview + auth data to a JSON fixture file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(DEFAULT_OUTPUT),
            help=f"Output path (default: {DEFAULT_OUTPUT})",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)

        models_to_dump = []
        for app_label in EXPORT_APPS:
            for model in apps.get_app_config(app_label).get_models():
                label = f"{app_label}.{model.__name__}".lower()
                if label not in EXCLUDE_MODELS:
                    models_to_dump.append(model)

        objects = []
        for model in models_to_dump:
            try:
                objects.extend(model.objects.all())
            except Exception as e:
                self.stderr.write(f"  Skipping {model.__name__}: {e}")

        data = serializers.serialize(
            "json",
            objects,
            indent=2,
            use_natural_foreign_keys=True,
            use_natural_primary_keys=True,
        )

        output.write_text(data)
        count = len(json.loads(data))
        self.stdout.write(self.style.SUCCESS(
            f"Exported {count} objects → {output}"
        ))
