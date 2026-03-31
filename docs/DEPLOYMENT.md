# FKCrypto Deployment Guide

Comprehensive guide for deploying and managing the FKCrypto trading system using Docker Compose.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [Service Descriptions](#service-descriptions)
- [Docker Setup Guide](#docker-setup-guide)
- [Configuration](#configuration)
- [Deployment Profiles](#deployment-profiles)
- [Production Configuration](#production-configuration)
- [Monitoring Setup](#monitoring-setup)
- [Metrics Reference](#metrics-reference)
- [Security Considerations](#security-considerations)
- [Backup and Recovery](#backup-and-recovery)
- [Troubleshooting](#troubleshooting)
- [Command Reference](#command-reference)

---

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| Disk | 50 GB SSD | 100+ GB SSD |
| OS | Linux, macOS, Windows (WSL2) | Linux (Ubuntu 22.04+) |

### Software Dependencies

- **Docker**: >= 24.0
- **Docker Compose**: >= 2.20 (v2 format)
- **Git**: >= 2.40

### Verify Installation

```bash
docker --version
docker compose version
```

---

## Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd fkcrypto

# Copy and configure environment
cp docker/.env.docker docker/.env
# Edit docker/.env with your configuration

# Start all core services
docker compose -f docker/docker-compose.yml up -d

# Verify deployment
docker compose -f docker/docker-compose.yml ps

# View logs
docker compose -f docker/docker-compose.yml logs -f gateway
```

Access points after deployment:

| Service | URL | Description |
|---------|-----|-------------|
| Nginx (Main) | http://localhost | Reverse proxy entry point |
| Dashboard | http://localhost:8501 | Streamlit monitoring UI |
| Gateway API | http://localhost:8000 | Trading orchestrator API |
| Freqtrade | http://localhost:8080 | Order execution engine |

---

## Architecture Overview

FKCrypto uses a microservices architecture orchestrated by Docker Compose. All services communicate over the isolated `fkcrypto-network` bridge network.

```
┌─────────────────────────────────────────────────────────────┐
│                         Nginx (:80, :443)                    │
│                    Reverse Proxy + Rate Limiting             │
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
        /api/   │                         │   /
                ▼                         ▼
┌───────────────────────┐     ┌───────────────────────┐
│    Gateway (:8000)    │     │   Dashboard (:8501)   │
│  LangGraph + Agents   │     │    Streamlit UI       │
│   Metrics (:9090)     │     └───────────────────────┘
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐     ┌───────────────────────┐
│   Freqtrade (:8080)   │     │    Redis (:6379)      │
│  Order Execution      │     │   Message Bus/Cache   │
└───────────────────────┘     └───────────┬───────────┘
                                          │
                                ┌─────────┴─────────┐
                                │                   │
                                ▼                   ▼
                     ┌─────────────────┐  ┌─────────────────┐
                     │  PostgreSQL     │  │   Prometheus    │
                     │  (:5432)        │  │   (:9090)       │
                     │  TimescaleDB    │  │   Grafana(:3000)│
                     └─────────────────┘  └─────────────────┘
```

---

## Service Descriptions

### Core Services

#### Gateway

| Property | Value |
|----------|-------|
| Image | Custom (`Dockerfile.gateway`) |
| Ports | 8000 (API), 9090 (Metrics) |
| Purpose | Main trading orchestrator using LangGraph and AI agents |

Multi-stage Docker build with non-root user (`fkcrypto`). Includes health checks and automatic dependency waiting via `entrypoint.sh`.

**Features:**
- LangGraph-based workflow orchestration
- AI agent coordination for trading decisions
- Prometheus metrics export on port 9090
- Alembic database migration management

#### Freqtrade

| Property | Value |
|----------|-------|
| Image | `freqtradeorg/freqtrade:stable` |
| Ports | 8080 |
| Purpose | Order execution engine |

Handles actual order placement, position management, and exchange communication.

#### Redis

| Property | Value |
|----------|-------|
| Image | `redis:7-alpine` |
| Ports | 6379 |
| Purpose | Message bus and caching layer |

Provides pub/sub messaging between services and caching for frequently accessed data.

#### PostgreSQL (TimescaleDB)

| Property | Value |
|----------|-------|
| Image | `timescale/timescaledb:latest-pg16` |
| Ports | 5432 |
| Purpose | Time-series database for market data and trading records |

TimescaleDB extension enables efficient time-series data storage and querying for OHLCV data, trades, and analytics.

#### Dashboard

| Property | Value |
|----------|-------|
| Image | Custom (`Dockerfile.dashboard`) |
| Ports | 8501 |
| Purpose | Streamlit-based monitoring UI |

Real-time visualization of trading activity, portfolio performance, and system health.

#### Nginx

| Property | Value |
|----------|-------|
| Image | `nginx:alpine` |
| Ports | 80 (HTTP), 443 (HTTPS) |
| Purpose | Reverse proxy with security features |

**Features:**
- Rate limiting: 30r/s for API, 60r/s general
- Gzip compression for responses
- Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- Routing: `/api/` → Gateway, `/` → Dashboard

### Optional Services

#### LiteLLM

| Property | Value |
|----------|-------|
| Image | `ghcr.io/berriai/litellm:main-latest` |
| Ports | 4000 |
| Purpose | LLM proxy for unified model access |

Provides a unified interface for multiple LLM providers with rate limiting, cost tracking, and fallback configurations.

#### Prometheus

| Property | Value |
|----------|-------|
| Image | `prom/prometheus:latest` |
| Ports | 9090 |
| Purpose | Metrics collection and storage |

Scrapes metrics from gateway and other instrumented services.

#### Grafana

| Property | Value |
|----------|-------|
| Image | `grafana/grafana:latest` |
| Ports | 3000 |
| Purpose | Metrics visualization and dashboards |

Pre-configured dashboards for monitoring trading performance and system health.

---

## Docker Setup Guide

### 1. Directory Structure

```
docker/
├── docker-compose.yml      # Main compose configuration
├── .env.docker             # Environment variable defaults
├── Dockerfile.gateway      # Gateway service build
├── Dockerfile.dashboard    # Dashboard service build
├── entrypoint.sh           # Gateway startup script
├── nginx/
│   └── nginx.conf          # Nginx reverse proxy config
└── prometheus/
    └── prometheus.yml      # Prometheus scrape configuration
```

### 2. Environment Configuration

Copy the default environment file and customize:

```bash
cp docker/.env.docker docker/.env
```

Key variables to configure:

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_USER` | Database username | `fkcrypto` |
| `POSTGRES_PASSWORD` | Database password | `<secure-password>` |
| `POSTGRES_DB` | Database name | `fkcrypto` |
| `REDIS_PASSWORD` | Redis password | `<secure-password>` |
| `EXCHANGE_API_KEY` | Exchange API key | `<your-key>` |
| `EXCHANGE_API_SECRET` | Exchange API secret | `<your-secret>` |
| `OPENAI_API_KEY` | OpenAI API key (if using) | `<your-key>` |

### 3. Building Images

```bash
# Build all custom images
docker compose -f docker/docker-compose.yml build

# Build specific service
docker compose -f docker/docker-compose.yml build gateway

# Build without cache (fresh build)
docker compose -f docker/docker-compose.yml build --no-cache
```

### 4. Starting Services

```bash
# Start core services
docker compose -f docker/docker-compose.yml up -d

# Start with specific profile
docker compose -f docker/docker-compose.yml --profile monitoring up -d

# Start and view logs
docker compose -f docker/docker-compose.yml up
```

### 5. Verifying Deployment

```bash
# Check service status
docker compose -f docker/docker-compose.yml ps

# Check service health
docker compose -f docker/docker-compose.yml ps --format json | jq '.[].Health'

# Verify connectivity
curl http://localhost/api/health
```

---

## Configuration

### Gateway Configuration

The gateway uses `entrypoint.sh` for startup orchestration:

1. Waits for PostgreSQL to accept connections
2. Waits for Redis to accept connections
3. Runs Alembic database migrations
4. Starts the gateway application

**Health Check:**
- Endpoint: `/health`
- Interval: 30s
- Timeout: 10s
- Retries: 3

### Nginx Configuration

**Rate Limiting Zones:**

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=general:10m rate=60r/s;
```

**Routing Rules:**

| Path | Backend | Rate Limit |
|------|---------|------------|
| `/api/` | Gateway:8000 | 30r/s |
| `/` | Dashboard:8501 | 60r/s |

**Security Headers:**

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: default-src 'self'`

### Prometheus Configuration

Scrape targets configured in `docker/prometheus/prometheus.yml`:

- Gateway metrics endpoint (port 9090)
- Configurable scrape interval
- Service discovery via Docker labels

---

## Deployment Profiles

### Default Profile

Core trading services only:

- gateway
- freqtrade
- redis
- postgres
- dashboard
- nginx

```bash
docker compose -f docker/docker-compose.yml up -d
```

### Monitoring Profile

Adds observability stack:

- prometheus
- grafana

```bash
docker compose -f docker/docker-compose.yml --profile monitoring up -d
```

Access Grafana at `http://localhost:3000` (default credentials: admin/admin).

### LiteLLM Profile

Adds LLM proxy service:

- litellm

```bash
docker compose -f docker/docker-compose.yml --profile litellm up -d
```

### Combined Profiles

```bash
# Full stack with monitoring and LiteLLM
docker compose -f docker/docker-compose.yml --profile monitoring --profile litellm up -d
```

---

## Production Configuration

### TLS/SSL Setup

Configure HTTPS in nginx:

1. Obtain SSL certificates (Let's Encrypt recommended):

```bash
certbot certonly --standalone -d your-domain.com
```

2. Mount certificates in `docker-compose.yml`:

```yaml
nginx:
  volumes:
    - /etc/letsencrypt/live/your-domain.com:/etc/ssl/certs:ro
    - /etc/letsencrypt/live/your-domain.com:/etc/ssl/private:ro
```

3. Update `nginx.conf` to enable SSL:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/ssl/certs/fullchain.pem;
    ssl_certificate_key /etc/ssl/private/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
}
```

### Secrets Management

**Option 1: Docker Secrets**

```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt
  api_key:
    file: ./secrets/api_key.txt

services:
  gateway:
    secrets:
      - db_password
      - api_key
```

**Option 2: HashiCorp Vault**

Integrate Vault for dynamic secrets management:

```bash
# Install Vault agent sidecar
# Configure auto-auth and secret rendering
# Reference secrets in environment variables
```

### Resource Limits

Configure resource constraints in `docker-compose.yml`:

```yaml
services:
  gateway:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 4G
        reservations:
          cpus: '2.0'
          memory: 2G
```

### Log Aggregation

Configure logging driver for centralized log collection:

```yaml
services:
  gateway:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

For production, consider:
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Loki + Promtail + Grafana
- Cloud providers (CloudWatch, Stackdriver)

---

## Monitoring Setup

### Prometheus Configuration

1. Access Prometheus at `http://localhost:9090`
2. Verify targets at `http://localhost:9090/targets`
3. Query metrics using PromQL

### Grafana Dashboards

1. Access Grafana at `http://localhost:3000`
2. Add Prometheus data source:
   - URL: `http://prometheus:9090`
   - Access: Server (default)
3. Import pre-built dashboards or create custom ones

### Recommended Dashboards

- **Trading Performance**: Portfolio value, drawdown, win rate
- **System Health**: CPU, memory, disk usage per service
- **API Metrics**: Request rates, latency, error rates
- **LLM Usage**: Token consumption, costs, error rates

---

## Metrics Reference

All metrics exposed by the gateway on port 9090 (`/metrics` endpoint).

### Trading Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `signals_total` | Counter | Total trading signals generated |
| `decisions_total` | Counter | Total trading decisions made |
| `orders_executed` | Counter | Total orders successfully executed |
| `orders_rejected` | Counter | Total orders rejected |
| `portfolio_value` | Gauge | Current portfolio value |
| `drawdown_pct` | Gauge | Current drawdown percentage |

### Performance Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `agent_latency_ms` | Histogram | Agent decision latency in milliseconds |

### LLM Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `llm_calls_total` | Counter | Total LLM API calls made |
| `llm_errors_total` | Counter | Total LLM API errors |

### Example PromQL Queries

```promql
# Signals per minute
rate(signals_total[1m])

# Order success rate
orders_executed / (orders_executed + orders_rejected)

# P95 agent latency
histogram_quantile(0.95, rate(agent_latency_ms_bucket[5m]))

# LLM error rate
rate(llm_errors_total[5m]) / rate(llm_calls_total[5m])
```

---

## Security Considerations

### Network Security

- All services run on isolated `fkcrypto-network`
- Only nginx exposes ports to the host
- Internal service communication uses Docker DNS

### Container Security

- Gateway runs as non-root user (`fkcrypto`)
- Multi-stage builds minimize attack surface
- Alpine-based images where possible

### Application Security

- Rate limiting prevents API abuse
- Security headers mitigate common web vulnerabilities
- Database credentials should be rotated regularly

### Best Practices

1. **Never commit secrets** to version control
2. **Use strong passwords** for all services
3. **Enable TLS** for all external communication
4. **Regularly update** base images and dependencies
5. **Monitor logs** for suspicious activity
6. **Implement network policies** if using Kubernetes
7. **Scan images** for vulnerabilities before deployment

```bash
# Scan images for vulnerabilities
docker scout cve <image-name>
```

---

## Backup and Recovery

### PostgreSQL Backup

**Automated Backup Script:**

```bash
#!/bin/bash
BACKUP_DIR="/backups/postgres"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker compose -f docker/docker-compose.yml exec -T postgres \
  pg_dump -U $POSTGRES_USER $POSTGRES_DB | gzip > \
  "$BACKUP_DIR/fkcrypto_$TIMESTAMP.sql.gz"
```

**Restore from Backup:**

```bash
gunzip -c fkcrypto_20240101_120000.sql.gz | \
  docker compose -f docker/docker-compose.yml exec -T postgres \
  psql -U $POSTGRES_USER $POSTGRES_DB
```

### Redis Backup

Redis data persists in the `redis_data` volume. For point-in-time snapshots:

```bash
# Trigger RDB save
docker compose -f docker/docker-compose.yml exec redis redis-cli BGSAVE

# Copy RDB file
docker cp fkcrypto-redis-1:/data/dump.rdb ./backup/
```

### Volume Backup

Backup all persistent volumes:

```bash
# List volumes
docker volume ls | grep fkcrypto

# Backup specific volume
docker run --rm -v fkcrypto_postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres_data.tar.gz -C /data .
```

### Recovery Procedure

1. Stop all services: `docker compose down`
2. Restore volumes from backup
3. Start services: `docker compose up -d`
4. Verify data integrity
5. Run migrations if needed: `docker compose exec gateway alembic upgrade head`

---

## Troubleshooting

### Common Issues

#### Services Won't Start

```bash
# Check service logs
docker compose -f docker/docker-compose.yml logs gateway

# Check container status
docker compose -f docker/docker-compose.yml ps -a

# Inspect container
docker inspect fkcrypto-gateway-1
```

#### Database Connection Issues

```bash
# Verify PostgreSQL is running
docker compose -f docker/docker-compose.yml exec postgres pg_isready

# Check database exists
docker compose -f docker/docker-compose.yml exec postgres \
  psql -U $POSTGRES_USER -l

# Run migrations manually
docker compose -f docker/docker-compose.yml exec gateway alembic upgrade head
```

#### Redis Connection Issues

```bash
# Verify Redis is running
docker compose -f docker/docker-compose.yml exec redis redis-cli ping

# Check Redis memory usage
docker compose -f docker/docker-compose.yml exec redis redis-cli info memory
```

#### Gateway Health Check Failing

```bash
# Check gateway logs
docker compose -f docker/docker-compose.yml logs -f gateway

# Test health endpoint directly
curl http://localhost:8000/health

# Check if dependencies are ready
docker compose -f docker/docker-compose.yml exec gateway \
  python -c "import psycopg2; psycopg2.connect('postgresql://...')"
```

#### Nginx Routing Issues

```bash
# Test nginx configuration
docker compose -f docker/docker-compose.yml exec nginx nginx -t

# Check nginx logs
docker compose -f docker/docker-compose.yml logs -f nginx

# Verify upstream connectivity
docker compose -f docker/docker-compose.yml exec nginx \
  curl -s http://gateway:8000/health
```

### Debug Mode

Enable verbose logging:

```yaml
services:
  gateway:
    environment:
      - LOG_LEVEL=DEBUG
  nginx:
    environment:
      - NGINX_ACCESS_LOG=on
```

### Resource Issues

```bash
# Check container resource usage
docker stats

# Check disk usage
docker system df

# Clean up unused resources
docker system prune -a
```

---

## Command Reference

### Lifecycle Commands

```bash
# Start all services
docker compose -f docker/docker-compose.yml up -d

# Start with monitoring profile
docker compose -f docker/docker-compose.yml --profile monitoring up -d

# Start with LiteLLM profile
docker compose -f docker/docker-compose.yml --profile litellm up -d

# Start with all profiles
docker compose -f docker/docker-compose.yml --profile monitoring --profile litellm up -d

# Stop all services
docker compose -f docker/docker-compose.yml down

# Stop and remove volumes (WARNING: deletes all data)
docker compose -f docker/docker-compose.yml down -v

# Rebuild and restart
docker compose -f docker/docker-compose.yml up -d --build

# Restart specific service
docker compose -f docker/docker-compose.yml restart gateway
```

### Monitoring Commands

```bash
# View logs for all services
docker compose -f docker/docker-compose.yml logs -f

# View logs for specific service
docker compose -f docker/docker-compose.yml logs -f gateway

# View last 100 lines
docker compose -f docker/docker-compose.yml logs --tail=100 gateway

# Check service status
docker compose -f docker/docker-compose.yml ps

# View resource usage
docker stats
```

### Maintenance Commands

```bash
# Run database migrations
docker compose -f docker/docker-compose.yml exec gateway alembic upgrade head

# Access PostgreSQL shell
docker compose -f docker/docker-compose.yml exec postgres psql -U $POSTGRES_USER $POSTGRES_DB

# Access Redis CLI
docker compose -f docker/docker-compose.yml exec redis redis-cli

# Access gateway shell
docker compose -f docker/docker-compose.yml exec gateway sh

# Pull latest images
docker compose -f docker/docker-compose.yml pull

# Prune unused Docker resources
docker system prune -af --volumes
```

---

## Support

For issues and questions:

- **Documentation**: See project README and docs/
- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Use GitHub Discussions for questions

---

*Last updated: 2026-04-01*
