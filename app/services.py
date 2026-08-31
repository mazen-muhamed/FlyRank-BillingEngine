from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, Plan, UsageEvent, MonthlyRollup, Subscription, PaymentRecord
from app.billing import tokens_to_cents, get_plan_limits, compute_total_cost
from app.schemas import EventType
from app.config import settings


async def get_tenant_usage_summary(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Aggregate usage for the current month and return summary."""
    period = datetime.utcnow().strftime("%Y-%m")

    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return None

    plan_name = tenant.plan_status
    limits = get_plan_limits(plan_name)

    # Aggregate from raw usage events for the current period
    api_calls_stmt = select(func.coalesce(
        func.sum(case((UsageEvent.event_type == "api_call", UsageEvent.quantity), else_=0)), 0
    )).where(
        UsageEvent.tenant_id == tenant_id,
        func.to_char(UsageEvent.recorded_at, 'YYYY-MM') == period,
    )
    tokens_stmt = select(func.coalesce(
        func.sum(case(
            (UsageEvent.event_type.in_(["input_token", "cached_input_token", "output_token", "reasoning_token"]),
            UsageEvent.quantity),
            else_=0
        )), 0
    )).where(
        UsageEvent.tenant_id == tenant_id,
        func.to_char(UsageEvent.recorded_at, 'YYYY-MM') == period,
    )

    api_calls_result = await db.execute(api_calls_stmt)
    tokens_result = await db.execute(tokens_stmt)
    api_calls_used = api_calls_result.scalar_one() or 0
    tokens_used = tokens_result.scalar_one() or 0

    # Fall back to rollup if no raw events
    if api_calls_used == 0 and tokens_used == 0:
        rollup_result = await db.execute(
            select(MonthlyRollup).where(
                MonthlyRollup.tenant_id == tenant_id,
                MonthlyRollup.period_year_month == period,
            )
        )
        rollup = rollup_result.scalar_one_or_none()
        if rollup:
            api_calls_used = rollup.api_calls_used
            tokens_used = rollup.tokens_used

    total_cost = 0

    return {
        "tenant_id": str(tenant_id),
        "api_calls_used": api_calls_used,
        "api_calls_limit": limits["api_calls_limit"],
        "tokens_used": tokens_used,
        "tokens_limit": limits["tokens_limit"],
        "total_cost_cents": total_cost,
        "plan_status": plan_name,
    }


async def check_quota(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    requested_quantity: int,
    event_type: str,
) -> tuple[bool, str | None]:
    """Check if adding requested_quantity would exceed the tenant's quota.
    Returns (allowed, reject_reason_or_None)."""
    period = datetime.utcnow().strftime("%Y-%m")

    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return False, "Tenant not found"

    limits = get_plan_limits(tenant.plan_status)
    limit_key = "api_calls_limit" if event_type == "api_call" else "tokens_limit"
    limit = limits[limit_key]

    # Count current usage for this event type this month
    result = await db.execute(
        select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.event_type == event_type,
            func.to_char(UsageEvent.recorded_at, 'YYYY-MM') == period,
        )
    )
    current_used = result.scalar_one() or 0

    if current_used + requested_quantity > limit:
        return False, f"Quota exceeded: {current_used}/{limit} used. Request of {requested_quantity} would exceed limit."

    return True, None


async def handle_stripe_webhook(db: AsyncSession, payload: dict, signature: str) -> dict:
    """Verify Stripe webhook signature and process event.

    NOTE: Signature verification requires stripe library + STRIPE_WEBHOOK_SECRET.
    This is the handler skeleton — production code calls stripe.Webhook.construct_event().
    """
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        event = stripe.Webhook.construct_event(
            payload=str(payload),
            sig_header=signature,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature", "status": 400}
    except Exception as e:
        return {"error": str(e), "status": 400}

    event_type = event["type"]
    stripe_event_id = event["id"]

    # check if we already processed this Stripe event
    result = await db.execute(
        select(PaymentRecord).where(PaymentRecord.stripe_event_id == stripe_event_id)
    )
    if result.scalar_one_or_none():
        return {"status": "already_processed", "event_id": stripe_event_id}

    data = event["data"]

    # Process checkout.session.completed
    if event_type == "checkout.session.completed":
        session = data["object"]
        tenant_id_str = session.get("metadata", {}).get("tenant_id")
        if not tenant_id_str:
            return {"error": "Missing tenant_id in metadata", "status": 400}

        tenant_id = uuid.UUID(tenant_id_str)
        subscription_id = session.get("subscription")

        record = PaymentRecord(
            tenant_id=tenant_id,
            stripe_event_id=stripe_event_id,
            event_type=event_type,
            stripe_data=str(data),
        )
        db.add(record)

        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            result2 = await db.execute(select(Plan).where(Plan.name == "pro"))
            pro_plan = result2.scalar_one_or_none()
            if pro_plan:
                tenant.plan_id = pro_plan.id
                tenant.plan_status = "pro"
                if subscription_id:
                    tenant.stripe_subscription_id = subscription_id

        await db.flush()
        return {"status": "subscription_updated", "tenant_id": tenant_id_str}

    # Process customer.subscription.updated
    elif event_type == "customer.subscription.updated":
        sub = data["object"]
        subscription_id = sub.get("id")
        status = sub.get("status")
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        )
        sub_record = result.scalar_one_or_none()
        if sub_record:
            sub_record.status = status
            await db.flush()

        record = PaymentRecord(
            tenant_id=uuid.UUID(sub.get("metadata", {}).get("tenant_id", "00000000-0000-0000-0000-000000000000")),
            stripe_event_id=stripe_event_id,
            event_type=event_type,
            stripe_data=str(data),
        )
        db.add(record)
        await db.flush()
        return {"status": "subscription_updated", "event_id": stripe_event_id}

    # Process customer.subscription.deleted
    elif event_type == "customer.subscription.deleted":
        sub = data["object"]
        subscription_id = sub.get("id")
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        )
        sub_record = result.scalar_one_or_none()
        if sub_record:
            sub_record.status = "canceled"
            await db.flush()
        await db.flush()
        return {"status": "subscription_canceled", "event_id": stripe_event_id}

    return {"status": "unhandled", "event_type": event_type}
