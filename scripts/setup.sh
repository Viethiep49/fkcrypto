#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== FKCrypto Initial Setup ==="
echo ""

# Copy .env.example to .env if .env doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Generated random DB password..."
    RANDOM_PASS=$(openssl rand -base64 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i.bak "s/DB_PASSWORD=changeme/DB_PASSWORD=${RANDOM_PASS}/" .env
    rm -f .env.bak
    echo "DB password updated in .env"
else
    echo ".env already exists, skipping."
fi

# Create necessary directories
echo "Creating directories..."
mkdir -p docker/nginx/certs
mkdir -p data/postgres
mkdir -p data/redis
mkdir -p data/freqtrade/config
mkdir -p data/freqtrade/user_data
mkdir -p data/freqtrade/logs
mkdir -p data/freqtrade/trades
mkdir -p logs

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit .env and fill in your API keys (LLM, exchange, notifications)"
echo "2. For HTTPS: place SSL certs in docker/nginx/certs/ and uncomment HTTPS block in nginx.conf"
echo "3. Start with: docker compose -f docker/docker-compose.yml up -d"
echo "4. View logs: docker compose -f docker/docker-compose.yml logs -f"
echo ""
echo "Services will be available at:"
echo "  Dashboard:  http://localhost:8501"
echo "  Gateway:    http://localhost:8000"
echo "  Nginx:      http://localhost (port 80)"
echo "  Freqtrade:  http://localhost:8080"
