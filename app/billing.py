from datetime import datetime
from typing import Optional
import uuid
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, Plan, UsageEvent, MonthlyRollup, Subscription, PaymentRecord
from app.schemas import EventType, CostBreakdown
from app.config import settings

# Pricing constants in cents — pinned, auditable, match Stripe test mode rules
PRICING = {
    "api_call": 0,
    "input_token": 1,        # 1 cent per 1k tokens (stored in raw token units * rate)
    "cached_input_token": 0,   # in production ~0.1 cents per 1k; config as 1 tenth-cent unit = 0.1 cent
    "output_token": 3,         # 3 cents per 1,000 tokens
    "reasoning_token": 3,      # counted as output tokens
}

# Convert token count to cents using per-token rate (cents per 1 token)
_TOKENS_PER_THOUSAND = 1000


def tokens_to_cents(quantity: int, token_type: str) -> int:
    """Convert token quantity to integer cents. Input tokens are 1 cent per 1k."""
    rate_cents_per_1k = PRICING.get(token_type, 0)
    if rate_cents_per_1k == 0:
        return 0
    # quantity is raw token count divide by 1000 and round down to nearest cent
    return (quantity // _TOKENS_PER_THOUSAND) * rate_cents_per_1k


def compute_total_cost(events: list[dict]) -> CostBreakdown:
    """Compute cost from a list of {'event_type': ..., 'quantity': ...} dicts."""
    breakdown = {k: 0 for k in PRICING}
    for e in events:
        t = e.get("event_type")
        q = e.get("quantity", 0)
        if t in breakdown:
            breakdown[t] += tokens_to_cents(q, t)
    total = sum(breakdown.values())
    return CostBreakdown(**breakdown, total_cents=total)


def get_plan_limits(plan_name: str) -> dict:
    if plan_name == "pro":
        return {"api_calls_limit": 10000, "tokens_limit": 1000000}
    return {"api_calls_limit": 1000, "tokens_limit": 100000}


async def get_or_create_free_plan(db: AsyncSession) -> Plan:
    """Ensure the Free plan exists in the DB (seed)."""
    result = await db.execute(select(Plan).where(Plan.name == "free"))
    plan = result.scalar_one_or_none()
    if not plan:
        plan = Plan(
            name="free",
            api_calls_limit=1000,
            api_tokens_limit=100000,
            price_per_month_cents=0,
            stripe_price_id="price_free_tier",
        )
        db.add(plan)
        await db.flush()
    return plan


async def get_or_create_pro_plan(db: AsyncSession) -> Plan:
    result = await db.execute(select(Plan).where(Plan.name == "pro"))
    plan = result.scalar_one_or_none()
    if not plan:
        plan = Plan(
            name="pro",
            api_calls_limit=10000,
            api_tokens_limit=1000000,
            price_per_month_cents=999,
            stripe_price_id="price_pro_tier",
        )
        db.add(plan)
        await db.flush()
    return plan


async def get_or_create_tenant(db: AsyncSession, name: str, email: str) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.email == email))
    tenant = result.scalar_one_or_none()
    if not tenant:
        plan = await get_or_create_free_plan(db)
        tenant = Tenant(name=name, email=email, plan_id=plan.id, plan_status="free")
        db.add(tenant)
        await db.flush()
    return tenant


def build_rollup_key() -> str:
    return datetime.utcnow().strftime("%Y-%m")


async def get_or_create_rollup(db: AsyncSession, tenant_id: uuid.UUID, plan_id: uuid.UUID) -> MonthlyRollup:
    period = build_rollup_key()
    result = await db.execute(
        select(MonthlyRollup).where(
            MonthlyRollup.tenant_id == tenant_id,
            MonthlyRollup.period_year_month == period,
        )
    )
    rollup = result.scalar_one_or_none()
    if not rollup:
        rollup = MonthlyRollup(
            tenant_id=tenant_id,
            plan_id=plan_id,
            period_year_month=period,
            api_calls_limit=1000,
            tokens_limit=100000,
        )
        db.add(rollup)
        await db.flush()
    return rollup


async def record_usage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    event_type: str,
    quantity: int,
    idempotency_key: str,
) -> tuple[UsageEvent, bool]:
    """Record usage event. Returns (event, is_duplicate). Duplicate = same key + type already exists."""
    # Idempotency check: same idempotency_key + event_type = one event only
    result = await db.execute(
        select(UsageEvent).where(
            UsageEvent.idempotency_key == idempotency_key,
            UsageEvent.event_type == event_type,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, True  

    event = UsageEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        quantity=quantity,
        idempotency_key=idempotency_key,
        cost_cents=tokens_to_cents(quantity, event_type),
    )
    db.add(event)
    await db.flush()
    return event, False


async def update_rollup_after_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    event_type: str,
    quantity: int,
) -> MonthlyRollup:
    """Add quantity to the current month's rollup."""
    rollup = await get_or_create_rollup(db, tenant_id, plan_id)
    if event_type in ("api_call",):
        rollup.api_calls_used += quantity
    else:
        rollup.tokens_used += quantity
    await db.flush()
    return rollup
