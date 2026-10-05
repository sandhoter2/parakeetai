#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input

# ── 1. Export existing data before any schema changes ───────────────────────
FIXTURE="fixtures/db_backup.json"

if python manage.py check --database default --silently-deprecate-setting DATABASES 2>/dev/null; then
  echo ">>> Exporting current data to $FIXTURE ..."
  python manage.py export_db --output "$FIXTURE" || echo "    (export skipped — DB may be empty)"
else
  echo ">>> DB not reachable for pre-migration export, skipping."
fi

# ── 2. Run migrations ────────────────────────────────────────────────────────
echo ">>> Running migrations ..."
python manage.py migrate --no-input

# ── 3. Reload data after migration ──────────────────────────────────────────
if [ -f "$FIXTURE" ]; then
  echo ">>> Loading data from $FIXTURE ..."
  python manage.py loaddata "$FIXTURE" && echo "    Data restored." \
    || echo "    loaddata failed (schema mismatch?) — continuing without restore."
else
  echo ">>> No fixture found at $FIXTURE — starting with empty DB."
fi
