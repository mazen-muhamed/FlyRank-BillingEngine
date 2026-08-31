from datetime import datetime, timedelta
import uuid

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, Tenant, Subscription


async def seed(db: AsyncSession) -> None:
    """Create seed data: Free/Pro plans and a demo tenant."""
    # Plans
    free_plan = await _get_or_create(db, "free", 1000, 100000, 0, "price_free_tier")
    pro_plan = await _get_or_create(db, "pro", 10000, 1000000, 999, "price_pro_tier")

    # Demo tenant on free plan
    result = await db.execute(select(Tenant).where(Tenant.email == "demo@flyrank.dev"))
    if not result.scalar_one_or_none():
        tenant = Tenant(
            name="Demo Tenant",
            email="demo@flyrank.dev",
            plan_id=free_plan.id,
            plan_status="free",
            stripe_customer_id="cus_demo_001",
        )
        db.add(tenant)
        await db.flush()

        sub = Subscription(
            tenant_id=tenant.id,
            plan_id=free_plan.id,
            stripe_subscription_id="sub_demo_001",
            status="active",
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + timedelta(days=30),
        )
        db.add(sub)
        await db.flush()

    await db.commit()
    print("Seed complete: Free plan, Pro plan, Demo tenant")


async def _get_or_create(db, name, api_calls, api_tokens, price, stripe_price_id):
    result = await db.execute(select(Plan).where(Plan.name == name))
    plan = result.scalar_one_or_none()
    if not plan:
        plan = Plan(
            name=name,
            api_calls_limit=api_calls,
            api_tokens_limit=api_tokens,
            price_per_month_cents=price,
            stripe_price_id=stripe_price_id,
        )
        db.add(plan)
        await db.flush()
    return plan