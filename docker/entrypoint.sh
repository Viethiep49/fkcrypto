#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until pg_isready -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" -U "${DB_USER:-fkcrypto}"; do
    sleep 2
done
echo "PostgreSQL is ready."

echo "Waiting for Redis..."
until redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" ping | grep -q PONG; do
    sleep 2
done
echo "Redis is ready."

echo "Running database migrations..."
python -m alembic upgrade head
echo "Migrations complete."

echo "Starting FKCrypto gateway..."
exec "$@"
