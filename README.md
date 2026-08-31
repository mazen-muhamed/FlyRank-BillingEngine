# FlyRank — Usage Metering & Billing Engine

Every billable action records **one** usage event (idempotency is DB-enforced), usage is
checked against the tenant's plan **before** the action (429/402 honesty), and cost is
computed in **integer cents** (never a float).

## Architecture

```
Client ──POST /api/v1/generate──▶ router ──▶ service ──▶ repository
                                   (main.py)  (meter_service)  (usage_repository)
                                        │  idempotency + quota check
                                        ▼
                                  usage_events   ◀── UNIQUE(tenant_id, idempotency_key)
                                        │  ├─ 429 Too Many Requests (over quota)
                                        │  └─ 402 Payment Required  (plan lapsed)

Stripe Checkout ──POST /api/v1/checkout──▶ Stripe Checkout session (metadata.tenant_id)
Stripe ──POST /webhooks/stripe──▶ verify signature → enqueue Celery → 200 (never blocks)
                                 worker: dedupe by stripe_event_id → sync plan/status
```

## Project layout

```
app/
├── main.py                   # app assembly, static mount, exception handler
├── routers/                  # THIN HTTP handlers (no business logic)
│   ├── generate.py           #   POST /api/v1/generate
│   ├── usage.py              #   GET  /api/v1/usage/{tenant_id}
│   ├── checkout.py           #   POST /api/v1/checkout
│   ├── webhooks.py           #   POST /webhooks/stripe  (verify → enqueue → 200)
│   ├── tenants.py            #   tenants CRUD
│   └── plans.py              #   GET /api/v1/plans
├── services/                 # business logic
│   ├── meter_service.py      #   idempotent record + quota (429 vs 402) + cost
│   ├── cost_service.py       #   monthly usage rollup → {used, limit, cost_cents}
│   └── stripe_service.py     #   checkout session + signature verify + webhook processing
├── workers/                  # Celery (Shared Requirement #3)
│   ├── celery_app.py         #   broker = Redis
│   └── tasks.py              #   billing.process_stripe_event (dedupe + plan sync, retry)
├── repositories/             # ALL SQL/ORM — no raw queries in routers/services
│   └── usage_repository.py
├── billing.py                # integer-cents pricing constants + plan limits (pure domain)
├── models.py                 # SQLAlchemy tables (UUID ids)
├── schemas.py                # Pydantic boundary models
├── config.py                 # pydantic-settings (secrets from .env, gitignored)
├── database.py               # async engine (asyncpg)
├── seed.py                   # Free/Pro plans + demo tenant
└── static/index.html         # admin console (served at / and /static/index.html)
```

## Run

### Prerequisites
- Python 3.11+ (this stack's native wheels don't build on 3.14 — use a 3.11 venv)
- Postgres running (native install)
- Redis running (Celery broker)
- Stripe CLI (for local webhook forwarding) — test mode, free

### 1. Environment
Copy `.env.example` → `.env` and fill:
```
DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/billing
REDIS_URL=redis://localhost:6379/0
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO_ID=price_...     # your real Pro Stripe price
BASE_URL=http://localhost:8000
```
`.env` is gitignored — never commit secrets.

### 2. Install + migrate
```bash
python3 -m venv .venv && source .venv/bin/activate   
pip install -r requirements.txt                       # or: uv pip install -r requirements.txt
python -m alembic upgrade head                        # create schema (migrations/versions/0001_initial.py)
```

### 3. Run (3 processes)
```bash
# Terminal 1 — API (serves admin console at http://localhost:8000/)
uvicorn app.main:app --reload

# Terminal 2 — Redis (if not already up)
redis-server

# Terminal 3 — Celery worker (processes webhook events off the request path)
celery -A app.workers.celery_app.celery_app worker --loglevel=info

# Terminal 4 — Stripe webhook forwarding (optional, for local webhook testing)
stripe listen --forward-to localhost:8000/webhooks/stripe
```

### 4. Seed
Plans (Free/Pro) + a demo tenant auto-seed on startup.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/generate` | metered call: `{event_type, quantity, idempotency_key}` |
| GET | `/api/v1/usage/{tenant_id}` | monthly usage, limit, and cost |
| POST | `/api/v1/tenants` | create tenant |
| GET | `/api/v1/plans` | list plans + quotas |
| POST | `/api/v1/checkout` | create Stripe Checkout session (test mode) |
| POST | `/webhooks/stripe` | webhook — verify sig, enqueue, 200 |
| GET | `/api/v1/cost-breakdown` | pinned pricing constants |

## Plans
- **Free** — 1,000 API calls/mo, 100,000 AI tokens/mo, $0
- **Pro** — 10,000 API calls/mo, 1,000,000 AI tokens/mo, $9.99

## Idempotency guarantees
- `usage_events` — `UNIQUE(tenant_id, idempotency_key)`: a retried key returns the **original** result, never a double-charge (DB-enforced, race-proof).
- `payment_records` — `UNIQUE(stripe_event_id)`: replayed webhooks are no-ops.
- Webhook returns **200 even on a dedupe-skip** so Stripe stops retrying.

## Pricing rules (PROBE 5)
- Cached input tokens are **cheaper** than fresh input.
- Reasoning tokens are priced **as output** tokens.
- Categories are summed independently (integer cents; floats never touch money).

## Acceptance probe results
See `EVIDENCE.md` for the captured curl transcripts: idempotency, quota 429, forged-webhook 400,
pricing rollup, and bad-input 4xx.

Capstone_UI.png
Stripe.png