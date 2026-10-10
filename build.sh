#!/usr/bin/env bash
# build.sh — runs on every Render deployment
# Flow: install → collectstatic → check DB → migrate → seed templates
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

# ── 2. Create superuser before migrations so backfill (0013) finds the admin ──
echo ">>> Creating superuser (if not exists) ..."
python manage.py createsuperuser --noinput || true

# ── 3. Run migrations (creates tables; 0010 seeds templates for existing users) ──
echo ">>> Running migrations ..."
python manage.py migrate --no-input

# ── 3. Seed default templates for any user who has none ──────────────────────
echo ">>> Seeding missing templates ..."
python manage.py seed_templates

# ── 4. Seed initial Jira board tasks (no-op if already seeded) ───────────────
echo ">>> Seeding task board ..."
python manage.py seed_tasks
echo "    Done."
