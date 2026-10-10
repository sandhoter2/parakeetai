#!/usr/bin/env bash
# backup.sh — dump live DB to fixtures/db_backup.json before every deployment
# Usage: ./backup.sh
# Run this locally while pointed at the production DB (MYSQL_* env vars set),
# commit the fixture, then git push + deploy.

set -euo pipefail

FIXTURE="fixtures/db_backup.json"

echo ">>> Backing up DB to $FIXTURE ..."

python3 manage.py dumpdata \
  --natural-foreign \
  --natural-primary \
  --exclude=contenttypes \
  --exclude=admin.logentry \
  --exclude=sessions.session \
  --indent 2 \
  -o "$FIXTURE"

echo ">>> Backup complete: $FIXTURE"
echo ">>> Rows in fixture: $(python3 -c "import json; d=json.load(open('$FIXTURE')); print(len(d))")"
echo ""
echo ">>> Next steps:"
echo "    git add fixtures/db_backup.json"
echo "    git commit -m 'chore: pre-deploy DB backup'"
echo "    git push origin main"
echo "    # then trigger deploy"
