#!/bin/bash
# Quick start script for ParakeetAI Local
set -e

cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  echo "Creating .env from example..."
  cp .env.example .env
  echo ""
  echo "⚠️  Edit .env and add your ANTHROPIC_API_KEY before starting."
  echo "   nano .env"
  exit 1
fi

echo "🦜 Starting ParakeetAI Local..."
python3 manage.py migrate --run-syncdb 2>/dev/null || true
python3 manage.py runserver 8000
