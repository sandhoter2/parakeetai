#!/usr/bin/env bash
# build.sh — runs on every Render deployment
# Flow: install → collectstatic → check DB → migrate → superuser → seed
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input

# ── 1. Check database connection ─────────────────────────────────────────────
echo ">>> Checking database connection ..."
python - <<'PYCHECK'
import os, sys, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "local_parakeet.settings")
django.setup()
from django.db import connection
try:
    connection.ensure_connection()
    print("    DB connection OK:", connection.settings_dict["ENGINE"])
except Exception as e:
    print(f"    DB connection FAILED: {e}", file=sys.stderr)
    sys.exit(1)
PYCHECK

# ── 2. Run migrations (must happen before superuser creation) ─────────────────
echo ">>> Running migrations ..."
python manage.py migrate --no-input

# ── 3. Create or update superuser ────────────────────────────────────────────
echo ">>> Creating/updating superuser ..."
python - <<'PYSU'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "local_parakeet.settings")
django.setup()
from django.contrib.auth.models import User
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "superadmin")
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
if not password:
    print("    DJANGO_SUPERUSER_PASSWORD not set — skipping.")
else:
    u, created = User.objects.get_or_create(username=username)
    u.set_password(password)
    u.is_staff = True
    u.is_superuser = True
    if email:
        u.email = email
    u.save()
    print(f"    Superuser '{username}' {'created' if created else 'updated'}.")
PYSU

# ── 4. Seed default templates for any user who has none ──────────────────────
echo ">>> Seeding missing templates ..."
python manage.py seed_templates

# ── 5. Seed initial Jira board tasks (no-op if already seeded) ───────────────
echo ">>> Seeding task board ..."
python manage.py seed_tasks
echo "    Done."
