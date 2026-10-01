#!/bin/bash
# ==============================================================================
# Automated Production Deployment Script for InstaPay Portal on aaPanel / Ubuntu
# ==============================================================================

set -e

GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m" # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${GREEN}   InstaPay Verification Microservice Deployment    ${NC}"
echo -e "${BLUE}====================================================${NC}"

# 1. Check Docker & Docker Compose availability
if ! command -v docker &> /dev/null; then
    echo -e "${RED}[ERROR] Docker is not installed on this server.${NC}"
    echo -e "${YELLOW}Please install Docker from aaPanel App Store or run: curl -fsSL https://get.docker.com | sh${NC}"
    exit 1
fi

# 2. Ensure .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[!] .env not found. Creating from .env.example...${NC}"
    cp .env.example .env
    echo -e "${GREEN}[+] .env created. Please review API keys in .env${NC}"
fi

# 3. Ensure persistent data directory exists
mkdir -p ./data
chmod 777 ./data

# If a local instapay.db exists in root and not yet in data/, copy it to preserve existing data
if [ -f "instapay.db" ] && [ ! -f "data/instapay.db" ]; then
    echo -e "${BLUE}[*] Migrating root instapay.db to ./data/instapay.db...${NC}"
    cp instapay.db data/instapay.db
    chmod 666 data/instapay.db
fi

# 4. Build and run Docker container
echo -e "${BLUE}[*] Building and starting InstaPay container...${NC}"
if docker compose version &> /dev/null; then
    docker compose down || true
    docker compose up -d --build
elif command -v docker-compose &> /dev/null; then
    docker-compose down || true
    docker-compose up -d --build
else
    echo -e "${RED}[ERROR] Neither 'docker compose' nor 'docker-compose' found.${NC}"
    exit 1
fi

# 5. Verify Health Check
echo -e "${BLUE}[*] Waiting for container initialization...${NC}"
HEALTH_OK=false
HEALTH_RESP=""
for i in {1..12}; do
    HEALTH_RESP=$(curl -s http://127.0.0.1:8000/health || echo "FAILED")
    if [[ "$HEALTH_RESP" == *"healthy"* ]] || [[ "$HEALTH_RESP" == *"ok"* ]] || [[ "$HEALTH_RESP" == *"status"* ]]; then
        HEALTH_OK=true
        break
    fi
    sleep 1
done

if [ "$HEALTH_OK" = true ]; then
    echo -e "${GREEN}====================================================${NC}"
    echo -e "${GREEN}  ✓ Deployment Successful! Microservice is Healthy! ${NC}"
    echo -e "${GREEN}====================================================${NC}"
    echo -e "${BLUE}Local Port:${NC} http://127.0.0.1:8000"
    echo -e "${BLUE}Health Check:${NC} http://127.0.0.1:8000/health"
    echo -e "${YELLOW}Live URL:${NC} https://insta.saf7etna.dpdns.org"
else
    echo -e "${YELLOW}[!] Container started, but health check returned:${NC} $HEALTH_RESP"
    echo -e "Check logs with: docker logs -f instapay-portal"
fi
