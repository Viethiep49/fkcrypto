#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "Running database migrations..."
python -m alembic upgrade head
echo "Migrations complete."
