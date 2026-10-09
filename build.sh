#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input

FIXTURE="fixtures/db_backup.json"

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

# ── 2. Run migrations ────────────────────────────────────────────────────────
echo ">>> Running migrations ..."
python manage.py migrate --no-input

# ── 3. Load fixture only if tables are empty (first deploy / fresh DB) ───────
FIXTURE="fixtures/db_backup.json"

if [ -f "$FIXTURE" ]; then
  echo ">>> Checking if DB is empty ..."
  IS_EMPTY=$(python - <<'PYEMPTY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "local_parakeet.settings")
django.setup()
from interview.models import InterviewSession
from django.contrib.auth.models import User
print("yes" if not User.objects.exists() and not InterviewSession.objects.exists() else "no")
PYEMPTY
)

  if [ "$IS_EMPTY" = "yes" ]; then
    echo ">>> DB is empty — loading initial data from $FIXTURE ..."
    python manage.py loaddata "$FIXTURE" && echo "    Initial data loaded." \
      || echo "    loaddata failed (fixture may be stale) — starting fresh."
  else
    echo ">>> DB already has data — skipping fixture load."
  fi
else
  echo ">>> No fixture at $FIXTURE — starting with empty DB."
fi
