import uuid
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant, Plan, UsageEvent, MonthlyRollup, Subscription, PaymentRecord


async def get_tenant_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def get_first_tenant(db: AsyncSession) -> Tenant | None:
    result = await db.execute(select(Tenant).limit(1))
    return result.scalar_one_or_none()


async def get_tenant_by_email(db: AsyncSession, email: str) -> Tenant | None:
    result = await db.execute(select(Tenant).where(Tenant.email == email))
    return result.scalar_one_or_none()


async def create_tenant(db: AsyncSession, name: str, email: str, plan_id=None) -> Tenant:
    tenant = Tenant(name=name, email=email, plan_id=plan_id, plan_status="free")
    db.add(tenant)
    await db.flush()
    return tenant

async def get_plan_by_name(db: AsyncSession, name: str) -> Plan | None:
    result = await db.execute(select(Plan).where(Plan.name == name))
    return result.scalar_one_or_none()


async def get_plan_by_id(db: AsyncSession, plan_id: uuid.UUID) -> Plan | None:
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    return result.scalar_one_or_none()


async def list_active_plans(db: AsyncSession) -> list[Plan]:
    result = await db.execute(select(Plan).where(Plan.is_active == True))
    return list(result.scalars().all())


# Usage events 
async def get_usage_by_key(db: AsyncSession, tenant_id: uuid.UUID, key: str, event_type: str) -> UsageEvent | None:
    result = await db.execute(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == key,
            UsageEvent.event_type == event_type,
        )
    )
    return result.scalar_one_or_none()


async def insert_usage(db: AsyncSession, tenant_id, event_type, quantity, cost_cents, key) -> UsageEvent:
    event = UsageEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        quantity=quantity,
        cost_cents=cost_cents,
        idempotency_key=key,
    )
    db.add(event)
    await db.flush()
    return event


async def sum_usage_this_month(db: AsyncSession, tenant_id: uuid.UUID, event_type: str, period: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.event_type == event_type,
            func.to_char(UsageEvent.recorded_at, "YYYY-MM") == period,
        )
    )
    return result.scalar_one() or 0


async def api_and_token_totals(db: AsyncSession, tenant_id: uuid.UUID, period: str):
    """Return (api_calls_used, tokens_used) for a tenant in a period."""
    api = await db.execute(
        select(func.coalesce(
            func.sum(case((UsageEvent.event_type == "api_call", UsageEvent.quantity), else_=0)), 0
        )).where(
            UsageEvent.tenant_id == tenant_id,
            func.to_char(UsageEvent.recorded_at, "YYYY-MM") == period,
        )
    )
    tok = await db.execute(
        select(func.coalesce(
            func.sum(case(
                (UsageEvent.event_type.in_(["input_token", "cached_input_token", "output_token", "reasoning_token"]),
                UsageEvent.quantity),
                else_=0
            )), 0
        )).where(
            UsageEvent.tenant_id == tenant_id,
            func.to_char(UsageEvent.recorded_at, "YYYY-MM") == period,
        )
    )
    return api.scalar_one() or 0, tok.scalar_one() or 0


# Monthly rollups 
async def get_rollup(db: AsyncSession, tenant_id: uuid.UUID, period: str) -> MonthlyRollup | None:
    result = await db.execute(
        select(MonthlyRollup).where(
            MonthlyRollup.tenant_id == tenant_id,
            MonthlyRollup.period_year_month == period,
        )
    )
    return result.scalar_one_or_none()


async def create_rollup(db: AsyncSession, tenant_id, plan_id, period, api_limit, token_limit) -> MonthlyRollup:
    rollup = MonthlyRollup(
        tenant_id=tenant_id,
        plan_id=plan_id,
        period_year_month=period,
        api_calls_limit=api_limit,
        tokens_limit=token_limit,
    )
    db.add(rollup)
    await db.flush()
    return rollup


# Webhook / payments 
async def get_payment_by_event(db: AsyncSession, stripe_event_id: str) -> PaymentRecord | None:
    result = await db.execute(select(PaymentRecord).where(PaymentRecord.stripe_event_id == stripe_event_id))
    return result.scalar_one_or_none()


async def insert_payment(db: AsyncSession, tenant_id, stripe_event_id, event_type, stripe_data) -> PaymentRecord:
    record = PaymentRecord(
        tenant_id=tenant_id, stripe_event_id=stripe_event_id,
        event_type=event_type, stripe_data=str(stripe_data),
    )
    db.add(record)
    await db.flush()
    return record


async def get_subscription_by_id(db: AsyncSession, subscription_id: str) -> Subscription | None:
    result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == subscription_id))
    return result.scalar_one_or_none()
