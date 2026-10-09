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

# ── 2. Run migrations (creates tables; 0010 seeds templates for existing users) ──
echo ">>> Running migrations ..."
python manage.py migrate --no-input

# ── 3. Seed default templates for any user who has none ──────────────────────
echo ">>> Seeding missing templates ..."
python manage.py seed_templates
echo "    Done."
