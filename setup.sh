#!/usr/bin/env bash
set -euo pipefail

# Load environment variables from .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "============================================"
echo "FlyRank Capstone — Metering & Billing Engine"
echo "Setup & Test Script"
echo "============================================"

# 1. Start PostgreSQL
echo "Step 1: Starting PostgreSQL..."
cd docker && docker compose up -d && cd ..

echo "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
    if docker exec metering-postgres-1 pg_isready -U "${POSTGRES_USER:-postgres}" 2>/dev/null; then
        break
    fi
    sleep 1
done

# 2. Create database
echo "Step 2: Creating database..."
# Get DB variables from environment with sensible defaults
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-billing}"

# PostgreSQL doesn't support "CREATE DATABASE IF NOT EXISTS", so workaround:
docker exec metering-postgres-1 bash -c "psql -U '$POSTGRES_USER' -tc \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'\" | grep -q 1 || psql -U '$POSTGRES_USER' -c \"CREATE DATABASE \\\"$POSTGRES_DB\\\";\"" \
    && echo "Database $POSTGRES_DB ready."

# 3. Install deps
echo "Step 3: Installing Python dependencies..."
pip install -q -r requirements.txt 2>&1 | tail -5

# 4. Create tables
echo "Step 4: Creating database tables..."
cd migrations && python env.py || python -c "
from app.database import engine
from app.models import Base
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv
load_dotenv()
db_url = os.getenv('DATABASE_URL', f'postgresql://{os.getenv(\"POSTGRES_USER\", \"postgres\")}:{os.getenv(\"POSTGRES_PASSWORD\", \"postgres\")}@{os.getenv(\"POSTGRES_HOST\", \"localhost\")}:{os.getenv(\"POSTGRES_PORT\", \"5432\")}/{os.getenv(\"POSTGRES_DB\", \"billing\")}')
sync_engine = create_engine(db_url)
Base.metadata.create_all(bind=sync_engine)
print('Tables created.')
"
cd ..

# 5. Seed
echo "Step 5: Seeding database..."
python -c "from app.seed import seed; import asyncio; asyncio.run(seed())"

# 6. Start server
echo ""
echo "✅ Setup complete!"
echo "Start the server with: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "Quick test:"
echo "  curl -X POST http://localhost:8000/api/v1/generate \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"idempotency_key\": \"test-001\", \"event_type\": \"api_call\", \"quantity\": 5}'"
echo ""
echo "  curl http://localhost:8000/api/v1/usage/<tenant-id>"
